"""Demo use case: customer-support triage and resolution.

Everything here is offline and deterministic so the framework can be exercised (and tested)
without an LLM account. ``support_policy`` stands in for the model: it reads the conversation
and emits the same JSON decisions a real model would. Swap in ``CortexLLM`` (or any LLM that
follows the decision format) to run the same tools, guardrails and evaluation on a real model.
"""

from __future__ import annotations

import json
import re
from typing import Any, Sequence

from .agent import Agent, Guardrails, Tool
from .llm import LLM, ScriptedLLM

ORDER_RE = re.compile(r"\bA\d{4}\b")
OBS_RE = re.compile(r"^OBSERVATION\[tool=(?P<tool>[^\]]+)\]: (?P<body>.*)$", re.S)

KB_ARTICLES = [
    {
        "title": "Password reset",
        "keywords": {"password", "reset", "login", "sign-in", "forgot"},
        "body": "To reset your password, choose Forgot password on the sign-in page and follow the emailed link. Links expire after 30 minutes.",
    },
    {
        "title": "Shipping times",
        "keywords": {"shipping", "delivery", "long", "ship", "arrive"},
        "body": "Standard shipping takes 3 to 5 business days. Express shipping takes 1 to 2 business days.",
    },
    {
        "title": "Returns and refunds",
        "keywords": {"return", "returns", "policy", "refund"},
        "body": "Items can be returned within 30 days of delivery for a full refund.",
    },
]

ORDERS = {
    "A1001": {"status": "delivered", "amount": 49.0, "days_since_delivery": 5},
    "A1002": {"status": "delivered", "amount": 320.0, "days_since_delivery": 3},
    "A1003": {"status": "shipped", "amount": 79.0, "days_since_delivery": None},
    "A1004": {"status": "delivered", "amount": 45.0, "days_since_delivery": 45},
    # Flagged for fraud review. A careful agent should escalate; the demo policy does not check,
    # which is exactly the kind of error the evaluation is meant to surface.
    "A1005": {"status": "delivered", "amount": 80.0, "days_since_delivery": 10, "fraud_flag": True},
}


class DemoEnv:
    """In-memory systems the tools talk to."""

    def __init__(self) -> None:
        self.orders = {k: dict(v) for k, v in ORDERS.items()}
        self.refunds: list[dict] = []

    def get_order_status(self, order_id: str) -> dict:
        order = self.orders.get(order_id)
        if order is None:
            return {"error": f"order {order_id} not found"}
        return {"order_id": order_id, **order}

    def search_kb(self, query: str) -> dict:
        words = set(re.findall(r"[a-z\-]+", query.lower()))
        best = max(KB_ARTICLES, key=lambda a: len(a["keywords"] & words))
        if not best["keywords"] & words:
            return {"found": False}
        return {"found": True, "title": best["title"], "body": best["body"]}

    def issue_refund(self, order_id: str, amount: float) -> dict:
        refund = {"refund_id": f"REF-{len(self.refunds) + 1:04d}", "order_id": order_id, "amount": float(amount)}
        self.refunds.append(refund)
        return refund


def build_tools(env: DemoEnv) -> list[Tool]:
    return [
        Tool("get_order_status", "Look up an order. Args: order_id", env.get_order_status),
        Tool("search_kb", "Search the help-center knowledge base. Args: query", env.search_kb),
        Tool("issue_refund", "Refund an order. Args: order_id, amount", env.issue_refund, high_risk=True),
    ]


# --------------------------------------------------------------------------- policy


def _action(thought: str, tool: str, **args: Any) -> str:
    return json.dumps({"thought": thought, "action": {"tool": tool, "args": args}})


def _final(thought: str, answer: str, confidence: float = 0.9, escalate: bool = False) -> str:
    return json.dumps({"thought": thought, "final": {"answer": answer, "confidence": confidence, "escalate": escalate}})


def _observations(messages: Sequence[dict]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for m in messages:
        match = OBS_RE.match(m["content"]) if m["role"] == "user" else None
        if match:
            seen[match["tool"]] = json.loads(match["body"])
    return seen


def support_policy(messages: Sequence[dict]) -> str:
    """Rule-based stand-in for an LLM. Returns one JSON decision per call."""
    task = next(m["content"] for m in messages if m["role"] == "user")[len("TASK: "):]
    lower = task.lower()
    obs = _observations(messages)
    order_id = (ORDER_RE.findall(task) or [None])[0]

    if any(w in lower for w in ("lawyer", "legal", "sue ", "attorney")):
        return _final("Legal language; a human must handle this.", "Escalating to a human agent.", escalate=True)

    if "refund" in lower and order_id:
        order = obs.get("get_order_status")
        if order is None:
            return _action("Check the order before refunding.", "get_order_status", order_id=order_id)
        if "error" in order:
            return _final("Order not found.", f"I could not find order {order_id}.", escalate=True)
        refund = obs.get("issue_refund")
        if refund is not None:
            return _final("Refund done.", f"Refund {refund['refund_id']} issued for ${refund['amount']:.2f} on order {order_id}.")
        if order["status"] != "delivered":
            return _final("Not delivered.", f"Order {order_id} is not delivered yet, so it cannot be refunded.")
        if order["days_since_delivery"] > 30:
            return _final("Outside window.", f"Order {order_id} is outside the 30-day refund window, so the refund was declined.")
        return _action("Eligible, issuing refund.", "issue_refund", order_id=order_id, amount=order["amount"])

    if order_id and any(w in lower for w in ("where", "track", "status")):
        order = obs.get("get_order_status")
        if order is None:
            return _action("Look up the order.", "get_order_status", order_id=order_id)
        if "error" in order:
            return _final("Order not found.", f"I could not find order {order_id}.", escalate=True)
        return _final("Report status.", f"Order {order_id} is {order['status']}.")

    kb = obs.get("search_kb")
    if kb is None:
        return _action("Look for a help article.", "search_kb", query=task)
    if kb.get("found"):
        return _final("Answer from the knowledge base.", kb["body"])
    return _final("No article covers this.", "This needs a human.", confidence=0.3)


# ------------------------------------------------------------------------ assembly


def make_approver(refund_limit: float = 100.0):
    """Approve refunds up to ``refund_limit``; anything larger needs a human."""

    def approve(tool: str, args: dict) -> bool:
        return tool != "issue_refund" or float(args.get("amount", 0)) <= refund_limit

    return approve


def build_demo_agent(llm: LLM | None = None, refund_limit: float = 100.0) -> Agent:
    """A fresh agent with fresh demo state (so evaluation cases do not affect each other)."""
    env = DemoEnv()
    return Agent(
        llm=llm or ScriptedLLM(support_policy),
        tools=build_tools(env),
        guardrails=Guardrails(max_steps=6, max_cost_usd=0.25, min_confidence=0.7, approver=make_approver(refund_limit)),
    )
