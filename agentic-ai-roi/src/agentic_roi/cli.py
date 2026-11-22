"""Command line:  python -m agentic_roi.cli <command>   (or ``agentic-roi <command>``)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from .demo import build_demo_agent
from .evaluate import apply_measured, evaluate
from .roi import UseCase, calculate, format_report, priority_score, scenarios, sensitivity


def _load_json(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _money(x: float) -> str:
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def _print_roi(uc: UseCase, show_sensitivity: bool, show_scenarios: bool) -> None:
    print(format_report(uc, calculate(uc)))
    if show_sensitivity:
        print("\nSensitivity: NPV when each input moves -20% / +20% (largest swing first)")
        for row in sensitivity(uc):
            print(f"  {row['param']:<26} {_money(row['npv_at_minus']):>14} {_money(row['npv_at_plus']):>14}   swing {_money(row['swing'])}")
    if show_scenarios:
        print("\nScenarios")
        for name, r in scenarios(uc).items():
            payback = "none" if r.payback_month is None else f"month {r.payback_month}"
            print(f"  {name:<12} NPV {_money(r.npv):>14}   payback {payback}")


def cmd_roi(args) -> None:
    uc = UseCase.from_dict(_load_json(args.usecase))
    if args.json:
        print(json.dumps(asdict(calculate(uc)), indent=2))
        return
    _print_roi(uc, args.sensitivity, args.scenarios)


def cmd_eval(args) -> None:
    cases = _load_json(args.cases)
    report = evaluate(build_demo_agent, cases)
    print(report.summary())
    print("\nPer case")
    for r in report.results:
        mark = "ok " if r.correct else "BAD"
        note = f"  ({r.reason})" if r.reason else ""
        print(f"  [{mark}] {r.id:<4} expected {r.expected_status:<10} got {r.status:<10} steps {r.steps}{note}")
    if args.usecase:
        uc = UseCase.from_dict(_load_json(args.usecase))
        print("\n--- ROI with the ASSUMED agent performance ---")
        print(format_report(uc, calculate(uc)))
        measured = apply_measured(uc, report)
        print("\n--- ROI with the MEASURED agent performance ---")
        print(format_report(measured, calculate(measured)))


def cmd_demo(args) -> None:
    run = build_demo_agent().run(args.task)
    print(f"Status:     {run.status}" + (f" ({run.reason})" if run.reason else ""))
    print(f"Answer:     {run.answer}")
    print(f"Cost:       ${run.cost_usd:.4f}  ({run.input_tokens} in / {run.output_tokens} out tokens)")
    print("Steps:")
    for s in run.steps:
        what = f"{s.tool}({json.dumps(s.args)})" if s.tool else "final answer"
        print(f"  {s.index}. {what}")
    if args.audit:
        print("\nAudit log:")
        for entry in run.audit:
            print("  " + json.dumps(entry))


def cmd_score(args) -> None:
    scores = json.loads(args.scores)
    print(f"Priority score: {priority_score(scores)} / 100")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agentic-roi", description="Implement an agentic AI use case and measure its ROI")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("roi", help="Calculate ROI for a use-case JSON file")
    c.add_argument("usecase")
    c.add_argument("--sensitivity", action="store_true", help="show the sensitivity table")
    c.add_argument("--scenarios", action="store_true", help="show pessimistic / base / optimistic")
    c.add_argument("--json", action="store_true", help="machine-readable output")
    c.set_defaults(func=cmd_roi)

    c = sub.add_parser("eval", help="Evaluate the demo agent on labeled cases")
    c.add_argument("cases")
    c.add_argument("--usecase", help="also compare ROI using assumed vs measured performance")
    c.set_defaults(func=cmd_eval)

    c = sub.add_parser("demo", help="Run the demo agent on one task")
    c.add_argument("task")
    c.add_argument("--audit", action="store_true", help="print the audit log")
    c.set_defaults(func=cmd_demo)

    c = sub.add_parser("score", help="Prioritize a use case (criteria scored 1-5, as JSON)")
    c.add_argument("scores", help='e.g. \'{"business_value":4,"feasibility":3,"data_readiness":4,"risk":3,"strategic_fit":5}\'')
    c.set_defaults(func=cmd_score)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
