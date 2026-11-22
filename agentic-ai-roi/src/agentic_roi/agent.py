"""A small, governed agent loop: plan -> act -> observe, with guardrails and an audit trail.

The model answers every turn with ONE JSON object, either

    {"thought": "...", "action": {"tool": "name", "args": {...}}}
    {"thought": "...", "final": {"answer": "...", "confidence": 0.0-1.0, "escalate": false}}

Guardrails (the part that makes an agent safe enough to put a number on):
* step budget and spend budget per task
* allow-list of tools
* human approval for high-risk tools (default: deny, so the task is escalated)
* confidence threshold: low-confidence answers are handed to a human
* every decision, tool call and outcome is recorded in ``RunResult.audit``
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .llm import LLM

COMPLETED = "completed"
ESCALATED = "escalated"
BUDGET_EXCEEDED = "budget_exceeded"
MAX_STEPS = "max_steps"


@dataclass
class Tool:
    name: str
    description: str
    fn: Callable[..., Any]
    high_risk: bool = False

    def spec(self) -> str:
        risk = " [HIGH RISK: needs approval]" if self.high_risk else ""
        return f"- {self.name}: {self.description}{risk}"


@dataclass
class Guardrails:
    max_steps: int = 6
    max_cost_usd: float = 0.25
    min_confidence: float = 0.7
    allowed_tools: set[str] | None = None
    # approver(tool_name, args) -> True to allow a high-risk call. None means deny.
    approver: Callable[[str, dict], bool] | None = None


@dataclass
class Step:
    index: int
    thought: str = ""
    tool: str | None = None
    args: dict = field(default_factory=dict)
    observation: Any = None
    error: str | None = None


@dataclass
class RunResult:
    status: str
    answer: str = ""
    confidence: float = 0.0
    reason: str = ""
    steps: list[Step] = field(default_factory=list)
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    audit: list[dict] = field(default_factory=list)

    @property
    def completed(self) -> bool:
        return self.status == COMPLETED

    @property
    def tools_used(self) -> list[str]:
        return [s.tool for s in self.steps if s.tool]


class DecisionError(ValueError):
    """The model's reply was not a valid decision."""


SYSTEM_TEMPLATE = """You are an autonomous agent. Complete the task using the tools below.
Reply with ONE JSON object per turn and nothing else.

To use a tool:  {{"thought": "...", "action": {{"tool": "<name>", "args": {{...}}}}}}
To finish:      {{"thought": "...", "final": {{"answer": "...", "confidence": 0.0-1.0, "escalate": false}}}}

Set "escalate": true (or give low confidence) when you are unsure, the request is out of scope,
or policy requires a human. Never invent tool results.

Tools:
{tools}
"""


def parse_decision(text: str) -> dict:
    """Extract the first JSON object from model output and check it is a valid decision."""
    start = text.find("{")
    if start == -1:
        raise DecisionError("no JSON object found")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise DecisionError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(obj, dict):
        raise DecisionError("decision must be a JSON object")
    if isinstance(obj.get("final"), dict):
        return obj
    action = obj.get("action")
    if isinstance(action, dict) and isinstance(action.get("tool"), str):
        if not isinstance(action.get("args", {}), dict):
            raise DecisionError("action.args must be an object")
        return obj
    raise DecisionError('decision needs an "action" or a "final"')


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Agent:
    def __init__(self, llm: LLM, tools: list[Tool], guardrails: Guardrails | None = None):
        self.llm = llm
        self.tools = {t.name: t for t in tools}
        self.guardrails = guardrails or Guardrails()

    def _system_prompt(self) -> str:
        return SYSTEM_TEMPLATE.format(tools="\n".join(t.spec() for t in self.tools.values()))

    def run(self, task: str) -> RunResult:
        g = self.guardrails
        result = RunResult(status=MAX_STEPS)
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": f"TASK: {task}"},
        ]

        def log(event: str, **details: Any) -> None:
            result.audit.append({"ts": _now(), "event": event, **details})

        log("start", task=task)

        for index in range(1, g.max_steps + 1):
            response = self.llm.complete(messages)
            result.input_tokens += response.input_tokens
            result.output_tokens += response.output_tokens
            result.cost_usd += (
                response.input_tokens / 1000 * self.llm.price_in_per_1k
                + response.output_tokens / 1000 * self.llm.price_out_per_1k
            )
            if result.cost_usd > g.max_cost_usd:
                result.status, result.reason = BUDGET_EXCEEDED, f"spend limit ${g.max_cost_usd:.2f} exceeded"
                log("stop", status=result.status, reason=result.reason)
                return result

            step = Step(index=index)
            result.steps.append(step)
            messages.append({"role": "assistant", "content": response.text})

            try:
                decision = parse_decision(response.text)
            except DecisionError as exc:
                step.error = str(exc)
                log("invalid_decision", step=index, error=step.error)
                messages.append({"role": "user", "content": f"OBSERVATION[error]: {step.error}. Reply with valid JSON."})
                continue

            step.thought = str(decision.get("thought", ""))

            if "final" in decision:
                final = decision["final"]
                result.answer = str(final.get("answer", ""))
                result.confidence = float(final.get("confidence", 1.0))
                if final.get("escalate"):
                    result.status, result.reason = ESCALATED, "agent requested a human"
                elif result.confidence < g.min_confidence:
                    result.status = ESCALATED
                    result.reason = f"confidence {result.confidence:.2f} below {g.min_confidence:.2f}"
                else:
                    result.status = COMPLETED
                log("final", status=result.status, confidence=result.confidence, reason=result.reason)
                return result

            action = decision["action"]
            step.tool, step.args = action["tool"], action.get("args", {})
            tool = self.tools.get(step.tool)

            if tool is None or (g.allowed_tools is not None and step.tool not in g.allowed_tools):
                step.error = f"tool '{step.tool}' is not available"
                log("tool_blocked", step=index, tool=step.tool)
                messages.append({"role": "user", "content": f"OBSERVATION[error]: {step.error}"})
                continue

            if tool.high_risk:
                approved = bool(g.approver and g.approver(tool.name, step.args))
                log("approval", step=index, tool=tool.name, args=step.args, approved=approved)
                if not approved:
                    result.status = ESCALATED
                    result.reason = f"approval denied for high-risk tool '{tool.name}'"
                    log("stop", status=result.status, reason=result.reason)
                    return result

            try:
                step.observation = tool.fn(**step.args)
            except Exception as exc:  # tool failures are data for the agent, not crashes
                step.error = f"{type(exc).__name__}: {exc}"
                log("tool_error", step=index, tool=tool.name, error=step.error)
                messages.append({"role": "user", "content": f"OBSERVATION[tool={tool.name}]: {json.dumps({'error': step.error})}"})
                continue

            log("tool_call", step=index, tool=tool.name, args=step.args)
            messages.append(
                {"role": "user", "content": f"OBSERVATION[tool={tool.name}]: {json.dumps(step.observation, default=str)}"}
            )

        result.reason = f"no final answer within {g.max_steps} steps"
        log("stop", status=result.status, reason=result.reason)
        return result
