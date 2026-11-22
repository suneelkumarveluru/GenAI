"""Evaluation harness: run the agent over labeled cases and turn the results into ROI inputs.

This closes the loop. The ROI model needs an automation rate, an error rate and a cost per
task. Instead of guessing them, measure them on representative cases and feed them back in.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable

from .agent import COMPLETED, Agent, RunResult
from .roi import UseCase


@dataclass
class CaseResult:
    id: str
    expected_status: str
    status: str
    correct: bool
    cost_usd: float
    steps: int
    reason: str = ""


@dataclass
class EvalReport:
    results: list[CaseResult] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.results)

    @property
    def completed(self) -> int:
        return sum(1 for r in self.results if r.status == COMPLETED)

    @property
    def completed_correct(self) -> int:
        return sum(1 for r in self.results if r.status == COMPLETED and r.correct)

    @property
    def automation_rate(self) -> float:
        """Share of tasks the agent finished end to end without a human."""
        return self.completed / self.n if self.n else 0.0

    @property
    def error_rate_agent(self) -> float:
        """Share of agent-completed tasks that were wrong."""
        return (self.completed - self.completed_correct) / self.completed if self.completed else 0.0

    @property
    def escalation_rate(self) -> float:
        return 1.0 - self.automation_rate

    @property
    def accuracy(self) -> float:
        """Share of all cases handled correctly, counting correct escalations."""
        return sum(1 for r in self.results if r.correct) / self.n if self.n else 0.0

    @property
    def avg_cost_usd(self) -> float:
        return sum(r.cost_usd for r in self.results) / self.n if self.n else 0.0

    @property
    def avg_steps(self) -> float:
        return sum(r.steps for r in self.results) / self.n if self.n else 0.0

    def summary(self) -> str:
        return "\n".join(
            [
                f"Cases:                {self.n}",
                f"Automation rate:      {self.automation_rate:.0%}  ({self.completed} completed end to end)",
                f"Escalation rate:      {self.escalation_rate:.0%}",
                f"Error rate (agent):   {self.error_rate_agent:.0%}  of completed tasks",
                f"Overall accuracy:     {self.accuracy:.0%}  (correct outcome incl. correct escalations)",
                f"Avg LLM cost / task:  ${self.avg_cost_usd:.4f}",
                f"Avg steps / task:     {self.avg_steps:.1f}",
            ]
        )


def judge(run: RunResult, expect: dict) -> bool:
    """A case is correct when status matches and every expected phrase is in the answer."""
    if run.status != expect.get("status", COMPLETED):
        return False
    answer = run.answer.lower()
    if any(phrase.lower() not in answer for phrase in expect.get("answer_contains", [])):
        return False
    required_tools = expect.get("tools_used", [])
    return all(tool in run.tools_used for tool in required_tools)


def evaluate(agent_factory: Callable[[], Agent], cases: list[dict]) -> EvalReport:
    """Run each case on a fresh agent (fresh state) and score it."""
    report = EvalReport()
    for case in cases:
        run = agent_factory().run(case["task"])
        expect = case.get("expect", {})
        report.results.append(
            CaseResult(
                id=str(case.get("id", len(report.results) + 1)),
                expected_status=expect.get("status", COMPLETED),
                status=run.status,
                correct=judge(run, expect),
                cost_usd=run.cost_usd,
                steps=len(run.steps),
                reason=run.reason,
            )
        )
    return report


def apply_measured(uc: UseCase, report: EvalReport) -> UseCase:
    """Replace the assumed agent performance in ``uc`` with what the evaluation measured."""
    automation = report.automation_rate
    return replace(
        uc,
        automation_rate=automation,
        assist_rate=min(uc.assist_rate, 1.0 - automation),
        error_rate_agent=report.error_rate_agent,
        llm_cost_per_task=report.avg_cost_usd,
    )
