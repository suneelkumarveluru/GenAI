"""Run a self-contained three-batch demonstration and produce an HTML dashboard."""
import argparse
import json
from pathlib import Path
from ai_readiness import assess
from readiness_history import record, recent
from readiness_dashboard import render


def demo(output):
    source = Path(__file__).resolve().parent
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    contract = json.loads((source / "demo_contract.json").read_text(encoding="utf-8"))
    db = output / "history.sqlite"
    for name in ("baseline", "drift", "invalid"):
        report = record(db, assess(source / f"demo_{name}.csv", contract), contract["drift"])
        (output / f"{name}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"{name}: {'PASS' if report['passed'] else 'FAIL'}")
    (output / "dashboard.html").write_text(render(recent(db, contract["dataset"]), contract["dataset"]),
                                           encoding="utf-8")
    return recent(db, contract["dataset"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", help="New output directory")
    demo(parser.parse_args().output)
