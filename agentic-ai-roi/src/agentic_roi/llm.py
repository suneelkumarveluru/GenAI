"""LLM adapters.

The agent only needs ``complete(messages) -> LLMResponse`` plus per-1K-token prices, so any
provider can be plugged in. Included:

* ``ScriptedLLM``: deterministic, offline (tests, demos, evaluation of the framework itself)
* ``CortexLLM``:   Snowflake Cortex ``COMPLETE`` through a snowflake.connector connection
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

Message = dict  # {"role": "system" | "user" | "assistant", "content": str}


@dataclass
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLM(Protocol):
    price_in_per_1k: float
    price_out_per_1k: float

    def complete(self, messages: Sequence[Message]) -> LLMResponse: ...


def estimate_tokens(text: str) -> int:
    """Rough token estimate (about 4 characters per token) for providers that do not report usage."""
    return max(1, len(text) // 4)


def messages_to_prompt(messages: Sequence[Message]) -> str:
    parts = [f"{m['role'].upper()}: {m['content']}" for m in messages]
    parts.append("ASSISTANT:")
    return "\n\n".join(parts)


class ScriptedLLM:
    """Replays canned responses, or calls ``policy(messages) -> str`` for rule-based behavior."""

    def __init__(
        self,
        responses: Sequence[str] | Callable[[Sequence[Message]], str],
        price_in_per_1k: float = 0.002,
        price_out_per_1k: float = 0.006,
    ):
        self._policy = responses if callable(responses) else None
        self._queue = list(responses) if not callable(responses) else []
        self.price_in_per_1k = price_in_per_1k
        self.price_out_per_1k = price_out_per_1k
        self.calls = 0

    def complete(self, messages: Sequence[Message]) -> LLMResponse:
        self.calls += 1
        if self._policy is not None:
            text = self._policy(messages)
        else:
            if not self._queue:
                raise RuntimeError("ScriptedLLM ran out of responses")
            text = self._queue.pop(0)
        prompt = messages_to_prompt(messages)
        return LLMResponse(text, estimate_tokens(prompt), estimate_tokens(text))


class CortexLLM:
    """Snowflake Cortex adapter. ``conn`` is an open snowflake.connector connection.

    Prices are per 1K tokens; set them from your Snowflake credit consumption table so the
    ROI model reflects real spend.
    """

    def __init__(
        self,
        conn,
        model: str = "mistral-large2",
        price_in_per_1k: float = 0.005,
        price_out_per_1k: float = 0.005,
    ):
        self.conn = conn
        self.model = model
        self.price_in_per_1k = price_in_per_1k
        self.price_out_per_1k = price_out_per_1k

    def complete(self, messages: Sequence[Message]) -> LLMResponse:
        prompt = messages_to_prompt(messages)
        with self.conn.cursor() as cur:
            cur.execute("SELECT SNOWFLAKE.CORTEX.COMPLETE(%s, %s)", (self.model, prompt))
            text = str(cur.fetchone()[0])
        return LLMResponse(text, estimate_tokens(prompt), estimate_tokens(text))
