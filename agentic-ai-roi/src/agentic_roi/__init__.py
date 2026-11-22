"""agentic_roi: implement an agentic AI use case and prove (or disprove) its ROI."""

from .agent import Agent, Guardrails, RunResult, Tool
from .evaluate import EvalReport, apply_measured, evaluate
from .llm import CortexLLM, LLMResponse, ScriptedLLM
from .roi import ROIResult, UseCase, calculate, priority_score

__version__ = "0.1.0"

__all__ = [
    "Agent",
    "CortexLLM",
    "EvalReport",
    "Guardrails",
    "LLMResponse",
    "ROIResult",
    "RunResult",
    "ScriptedLLM",
    "Tool",
    "UseCase",
    "apply_measured",
    "calculate",
    "evaluate",
    "priority_score",
]
