# Implementation roadmap: from idea to scaled agent

Five stages. Each one has an exit criterion so you know when to move on, and when to stop.

## What makes it "agentic"

| Level | What it does | Human role |
| --- | --- | --- |
| Chatbot | Answers questions from a prompt | Acts on every answer |
| Copilot | Drafts or suggests inside a workflow | Reviews every output |
| **Agent** | Plans steps, calls tools, observes results, decides what to do next | Sets goals and limits, handles escalations |
| Multi-agent | Several agents with different roles hand work to each other | Governs the system |

The jump from copilot to agent is where value and risk both rise. An agent can change data and spend money, so it needs guardrails before it needs more capability.

## Stage 1: Select and size the use case

- List 5 to 10 candidate workflows. Good candidates are high-volume, rules-driven, tolerant of occasional escalation, and have a measurable baseline (handle time, error rate, cost per task).
- Score each with `priority_score` (business value, feasibility, data readiness, risk, strategic fit, each 1 to 5).
- For the top two, fill in a use-case JSON with honest, conservative inputs and run `roi`.

**Exit:** one use case with a positive NPV in the *pessimistic* scenario, or a clear reason to stop. If the case only works in the optimistic scenario, do not build it yet.

## Stage 2: Prepare data, access and governance

- Identify the systems the agent must read and write. Give it a service identity with least-privilege access, never a person's credentials.
- Check data quality and freshness for the fields the agent will rely on. Agents amplify bad data because they act on it.
- Classify actions: read-only, reversible write, irreversible or financial. Irreversible and financial actions are `high_risk` and need approval.
- Decide ownership: who reviews escalations, who owns the agent in production, who can switch it off.

**Exit:** a written tool list with risk levels, an approver for each high-risk tool, and named owners.

## Stage 3: Build the agent with guardrails

- Start with the smallest tool set that covers the happy path.
- Set step and spend budgets, a confidence threshold and an allow-list from day one (`Guardrails`).
- Make every tool idempotent where you can, and return structured errors the agent can read.
- Keep the audit log. It is what lets compliance, support and engineering answer "why did it do that?"

**Exit:** the agent completes the happy path, escalates instead of guessing, and every action is in the audit log.

## Stage 4: Evaluate before you trust

- Build 50 to 200 labeled cases from real history, including the ugly ones: ambiguous requests, missing data, policy edge cases, angry customers, items flagged for review.
- Run `evaluate`. Track automation rate, error rate on completed tasks, escalation rate, cost per task and steps per task.
- Read every incorrect case. The most valuable ones are *confident wrong answers*, because they bypass escalation.
- Feed measured values into the ROI model with `apply_measured` and compare to the assumed case.

**Exit:** measured NPV is still positive, the error rate is below what the business accepts for unattended work, and the confident-wrong cases have fixes (tighter tools, new rules, lower autonomy).

## Stage 5: Roll out, operate and re-measure

- Start in shadow mode (agent proposes, human acts), then assist mode (human approves), then autonomous for the cases that proved safe.
- Ramp volume gradually. The ROI model's `ramp_months` should match the rollout plan.
- Monitor the same metrics the evaluation produced, on live traffic: automation rate, error rate, escalation rate, spend per task, approval denials.
- Re-run the evaluation on every change to the model, prompts or tools. Treat it like a regression suite.
- Revisit the ROI quarterly with actuals. If payback slips, the sensitivity table tells you which input to chase.

**Exit:** live metrics within tolerance of the evaluated ones for a full quarter. Then pick the next use case.

## Cost categories to include in any ROI case

| Category | Examples |
| --- | --- |
| Build | Engineering, integration, security review, evaluation set creation |
| Run | LLM tokens, infrastructure, vector or search services, monitoring |
| People | Maintenance and prompt or tool upkeep, escalation handling, governance |
| Change | Training, process redesign, support for the people whose work changes |
| Risk | Cost of errors, rework, incidents, compliance exposure |

## Benefit categories

| Category | How to measure it |
| --- | --- |
| Productivity | Minutes saved per task times volume times loaded labor cost |
| Quality | Error rate before and after, times cost per error |
| Speed | Faster resolution, shorter cycle time, SLA credits avoided |
| Capacity | Work handled without new hires (count only if you would otherwise hire) |
| Revenue | Conversion or retention uplift you can attribute (use sparingly and conservatively) |

Count a benefit only if a named owner will confirm it in the P&L. Savings that never turn into reduced cost or extra output are not ROI.
