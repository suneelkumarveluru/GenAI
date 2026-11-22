"""Agent, guardrail and evaluation tests. Run:  python -m unittest discover -s tests -v"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentic_roi.agent import (  # noqa: E402
    BUDGET_EXCEEDED,
    COMPLETED,
    ESCALATED,
    MAX_STEPS,
    Agent,
    DecisionError,
    Guardrails,
    Tool,
    parse_decision,
)
from agentic_roi.demo import build_demo_agent  # noqa: E402
from agentic_roi.evaluate import apply_measured, evaluate  # noqa: E402
from agentic_roi.llm import ScriptedLLM  # noqa: E402
from agentic_roi.roi import UseCase, calculate  # noqa: E402


def act(tool, **args):
    return json.dumps({"thought": "t", "action": {"tool": tool, "args": args}})


def fin(answer="done", confidence=0.9, escalate=False):
    return json.dumps({"thought": "t", "final": {"answer": answer, "confidence": confidence, "escalate": escalate}})


ECHO = Tool("echo", "Echo text. Args: text", lambda text: {"echo": text})
DANGER = Tool("danger", "Risky. Args: n", lambda n: {"did": n}, high_risk=True)


class Parsing(unittest.TestCase):
    def test_parses_json_with_surrounding_prose(self):
        d = parse_decision('Sure! ' + fin("ok") + ' Anything else?')
        self.assertEqual(d["final"]["answer"], "ok")

    def test_rejects_garbage(self):
        for bad in ("no json", '{"thought": "x"}', '{"action": {"args": {}}}', "[1, 2]"):
            with self.assertRaises(DecisionError):
                parse_decision(bad)


class Loop(unittest.TestCase):
    def test_tool_then_final(self):
        agent = Agent(ScriptedLLM([act("echo", text="hi"), fin("hi back")]), [ECHO])
        r = agent.run("say hi")
        self.assertEqual(r.status, COMPLETED)
        self.assertEqual(r.tools_used, ["echo"])
        self.assertEqual(r.steps[0].observation, {"echo": "hi"})
        self.assertGreater(r.cost_usd, 0)

    def test_invalid_output_is_retried(self):
        agent = Agent(ScriptedLLM(["not json", fin()]), [ECHO])
        r = agent.run("x")
        self.assertEqual(r.status, COMPLETED)
        self.assertIsNotNone(r.steps[0].error)

    def test_unknown_tool_is_reported_not_crashed(self):
        agent = Agent(ScriptedLLM([act("nope"), fin()]), [ECHO])
        r = agent.run("x")
        self.assertEqual(r.status, COMPLETED)
        self.assertIn("not available", r.steps[0].error)

    def test_tool_exception_becomes_observation(self):
        boom = Tool("boom", "fails", lambda: 1 / 0)
        agent = Agent(ScriptedLLM([act("boom"), fin()]), [boom])
        r = agent.run("x")
        self.assertEqual(r.status, COMPLETED)
        self.assertIn("ZeroDivisionError", r.steps[0].error)

    def test_max_steps(self):
        agent = Agent(ScriptedLLM(lambda m: act("echo", text="loop")), [ECHO], Guardrails(max_steps=3))
        r = agent.run("x")
        self.assertEqual(r.status, MAX_STEPS)
        self.assertEqual(len(r.steps), 3)


class Guardrail(unittest.TestCase):
    def test_budget_exceeded(self):
        llm = ScriptedLLM(lambda m: act("echo", text="x"), price_in_per_1k=1000.0)
        r = Agent(llm, [ECHO], Guardrails(max_cost_usd=0.01)).run("x")
        self.assertEqual(r.status, BUDGET_EXCEEDED)

    def test_high_risk_denied_by_default(self):
        r = Agent(ScriptedLLM([act("danger", n=1)]), [DANGER]).run("x")
        self.assertEqual(r.status, ESCALATED)
        self.assertIn("approval denied", r.reason)

    def test_high_risk_approved(self):
        g = Guardrails(approver=lambda tool, args: args["n"] < 5)
        ok = Agent(ScriptedLLM([act("danger", n=1), fin()]), [DANGER], g).run("x")
        self.assertEqual(ok.status, COMPLETED)
        no = Agent(ScriptedLLM([act("danger", n=9)]), [DANGER], g).run("x")
        self.assertEqual(no.status, ESCALATED)

    def test_allow_list(self):
        g = Guardrails(allowed_tools={"echo"})
        r = Agent(ScriptedLLM([act("danger", n=1), fin()]), [ECHO, DANGER], g).run("x")
        self.assertEqual(r.status, COMPLETED)
        self.assertIn("not available", r.steps[0].error)

    def test_low_confidence_escalates(self):
        r = Agent(ScriptedLLM([fin("maybe", confidence=0.4)]), [ECHO]).run("x")
        self.assertEqual(r.status, ESCALATED)

    def test_explicit_escalation(self):
        r = Agent(ScriptedLLM([fin("human please", escalate=True)]), [ECHO]).run("x")
        self.assertEqual(r.status, ESCALATED)

    def test_audit_trail_records_decisions(self):
        g = Guardrails(approver=lambda t, a: True)
        r = Agent(ScriptedLLM([act("danger", n=1), fin()]), [DANGER], g).run("x")
        events = [e["event"] for e in r.audit]
        self.assertEqual(events, ["start", "approval", "tool_call", "final"])
        json.dumps(r.audit)  # must be serializable


class DemoAgent(unittest.TestCase):
    def test_small_refund_is_issued(self):
        r = build_demo_agent().run("Refund order A1001 please")
        self.assertEqual(r.status, COMPLETED)
        self.assertIn("issued", r.answer)

    def test_large_refund_needs_human(self):
        r = build_demo_agent().run("Refund order A1002 please")
        self.assertEqual(r.status, ESCALATED)

    def test_state_is_isolated_between_agents(self):
        a, b = build_demo_agent(), build_demo_agent()
        a.run("Refund order A1001 please")
        self.assertIn("REF-0001", b.run("Refund order A1001 please").answer)


class Evaluation(unittest.TestCase):
    def setUp(self):
        self.cases = json.loads((ROOT / "examples" / "ticket_eval_cases.json").read_text())
        self.report = evaluate(build_demo_agent, self.cases)

    def test_report_counts(self):
        self.assertEqual(self.report.n, len(self.cases))
        self.assertGreater(self.report.automation_rate, 0)
        self.assertLess(self.report.automation_rate, 1)

    def test_known_error_is_surfaced(self):
        # Case 11 (fraud-flagged order) is refunded by the demo policy but should be escalated.
        bad = [r for r in self.report.results if not r.correct]
        self.assertEqual([r.id for r in bad], ["11"])
        self.assertGreater(self.report.error_rate_agent, 0)

    def test_measured_values_flow_into_roi(self):
        uc = UseCase.from_dict(json.loads((ROOT / "examples" / "ticket_triage_usecase.json").read_text()))
        measured = apply_measured(uc, self.report)
        self.assertEqual(measured.automation_rate, self.report.automation_rate)
        self.assertEqual(measured.error_rate_agent, self.report.error_rate_agent)
        self.assertLessEqual(measured.automation_rate + measured.assist_rate, 1.0 + 1e-9)
        calculate(measured)  # must not raise


if __name__ == "__main__":
    unittest.main()
