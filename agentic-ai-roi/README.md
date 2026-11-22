# agentic-ai-roi

**How to implement agentic AI, and how to prove it pays off.**

A working reference implementation of the two halves of an agentic AI program:

1. **Build a governed agent** (plan, act, observe loop with tools, spend and step budgets, human approval for risky actions, confidence thresholds and an audit trail).
2. **Define and test an ROI framework** (cost-benefit model with NPV, payback, break-even automation rate, sensitivity and scenarios), then feed it with **measured** agent performance from an evaluation harness instead of guesses.

> The structure follows the title and theme of the guide "How To Implement Agentic AI: A Guide to Understanding Agentic AI and Defining an ROI Framework". It was built from that title, not from the guide's text, so treat the stages and formulas here as this project's own interpretation.

Standard library only. Python 3.10+.

## Why this exists

Most agentic AI pilots stall because nobody can answer two questions with evidence: *Is the agent good enough to run unattended?* and *Does it pay for itself?* This project connects the two. The evaluation harness measures the automation rate, error rate and cost per task. The ROI model turns those into money.

```
 use-case JSON ──┐
                 ├─► ROI model ──► NPV, ROI %, payback, break-even, sensitivity
 eval cases ─► agent + guardrails ─► measured automation / error / cost ─┘
```

## Quick start

```bash
cd agentic-ai-roi
export PYTHONPATH=src        # Windows PowerShell: $env:PYTHONPATH="src"

# 1. ROI of the example use case, with sensitivity and scenarios
python -m agentic_roi.cli roi examples/ticket_triage_usecase.json --sensitivity --scenarios

# 2. Run the demo agent on one task and see its audit log
python -m agentic_roi.cli demo "Refund order A1001 please" --audit

# 3. Evaluate the agent on 12 labeled cases and compare assumed vs measured ROI
python -m agentic_roi.cli eval examples/ticket_eval_cases.json --usecase examples/ticket_triage_usecase.json

# 4. Prioritize candidate use cases (each criterion scored 1-5)
python -m agentic_roi.cli score '{"business_value":4,"feasibility":3,"data_readiness":4,"risk":3,"strategic_fit":5}'

# Tests (38)
python -m unittest discover -s tests -v
```

## The ROI framework

For each month of the horizon:

| | |
| --- | --- |
| **Benefits** | Labor saved on tasks the agent completes end to end, plus labor saved where the agent drafts and a human reviews, plus the value of fewer errors (negative if the agent errs more than people), plus any other monthly benefit you can defend |
| **Run costs** | LLM cost on every task routed to the agent, rework on agent mistakes, infrastructure, and the people who maintain the agent |
| **Build** | One-time cost in month 0 |
| **Adoption** | Ramps linearly from 0% to 100% over `ramp_months` |

Outputs: **NPV**, **ROI %**, **payback month**, steady-state monthly economics, cost per task (manual vs agent), the **break-even automation rate** (how often the agent must finish tasks alone for NPV to reach zero), a **sensitivity table** (inputs moved by -20% and +20%) and **pessimistic / base / optimistic scenarios**.

Every input lives in one JSON file ([`examples/ticket_triage_usecase.json`](examples/ticket_triage_usecase.json)). Unknown fields are rejected so typos do not silently change the answer.

### What the example shows

With the example inputs (illustrative numbers, replace them with yours) the support agent has an NPV of about $1.0M over 36 months, pays back in month 8, and breaks even at an 11% automation rate against 55% modeled. Sensitivity shows the result is driven by volume, handle time and labor cost far more than by LLM spend, which is the usual finding: **token cost is rarely what makes or breaks the case**.

### Assumed vs measured

Running `eval ... --usecase ...` replaces the assumed automation rate, error rate and cost per task with values measured on the labeled cases. In the demo, one case (a fraud-flagged order the agent refunds when it should escalate) is a real error, so measured quality is worse than assumed and NPV drops from about $1.0M to about $0.76M. That gap is the point: it is the number you want before you scale.

> The demo agent uses a rule-based stand-in for the model so everything runs offline and deterministically. Its measured numbers show how the mechanism works. They are not a benchmark of any real LLM. Run the same cases with a real model to get real numbers (see below).

## The agent

[`agent.py`](src/agentic_roi/agent.py) runs a plan, act, observe loop. The model replies with one JSON decision per turn: call a tool, or give a final answer with a confidence score.

Guardrails, all configured in `Guardrails`:

| Guardrail | Behavior |
| --- | --- |
| Step budget | Stops after `max_steps`, hands the task to a human |
| Spend budget | Stops when estimated LLM spend for the task passes `max_cost_usd` |
| Tool allow-list | Blocks any tool not on the list |
| Human approval | Tools marked `high_risk` run only if the `approver` says yes. Default is deny, so the task escalates |
| Confidence threshold | Answers below `min_confidence` are escalated |
| Audit trail | Every start, tool call, approval, block and outcome is recorded as JSON |

Invalid model output and tool exceptions are fed back to the model as observations instead of crashing the run.

## Use a real LLM

Any object with `complete(messages) -> LLMResponse` and per-1K-token prices works. A Snowflake Cortex adapter is included:

```python
import snowflake.connector
from agentic_roi import CortexLLM
from agentic_roi.demo import build_demo_agent

conn = snowflake.connector.connect(connection_name="default")
agent = build_demo_agent(llm=CortexLLM(conn, model="mistral-large2"))
print(agent.run("Where is my order A1003?").answer)
```

Install the connector with `pip install -e ".[snowflake]"`. Set the adapter's token prices from your actual Snowflake credit consumption so the ROI model reflects real spend. To evaluate your own use case, replace the tools in [`demo.py`](src/agentic_roi/demo.py) with real ones, write labeled cases like [`ticket_eval_cases.json`](examples/ticket_eval_cases.json), and rerun `evaluate`.

## Implementation roadmap

See [`docs/roadmap.md`](docs/roadmap.md) for the five-stage path from use-case selection to scaled operation, with the exit criteria for each stage.

## Layout

```
src/agentic_roi/
  roi.py        ROI model, break-even, sensitivity, scenarios, use-case prioritization
  agent.py      governed agent loop, guardrails, audit trail
  llm.py        LLM interface, offline ScriptedLLM, Snowflake Cortex adapter
  evaluate.py   evaluation harness and measured-to-ROI bridge
  demo.py       support-triage demo: tools, rule-based policy, approver
  cli.py        roi / eval / demo / score commands
examples/       use-case inputs and labeled evaluation cases
tests/          38 offline tests
docs/roadmap.md
```
