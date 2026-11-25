"""Transactional SQLite history with a fixed, approved baseline per contract."""
import json
import argparse
import sqlite3
from contextlib import closing
from pathlib import Path
from readiness_profile import compare


def _schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY,
        dataset TEXT NOT NULL,
        contract_hash TEXT NOT NULL,
        evaluated_at TEXT NOT NULL,
        passed INTEGER NOT NULL,
        is_baseline INTEGER NOT NULL,
        report TEXT NOT NULL
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS runs_lookup
        ON runs(dataset, contract_hash, is_baseline, id)""")


def record(path, report, policy, promote=False):
    """Fail closed on drift; never replace a baseline without explicit approval."""
    with closing(sqlite3.connect(path, timeout=30)) as db, db:
        _schema(db)
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute(
            """SELECT id, report FROM runs
               WHERE dataset=? AND contract_hash=? AND is_baseline=1
               ORDER BY id DESC LIMIT 1""",
            (report["dataset"], report["contract_hash"]),
        ).fetchone()
        baseline = False
        if previous:
            metrics, violations = compare(report, json.loads(previous[1]), policy)
            report["drift"] = {"status": "compared", "baseline_id": previous[0], **metrics}
            if promote and report["passed"]:
                baseline = True
                report["drift"]["status"] = "baseline_promoted"
                report["drift"]["overridden_violations"] = violations
            else:
                report["violations"].update(violations)
        else:
            baseline = report["passed"]
            report["drift"] = {"status": "baseline_created" if baseline else "no_baseline"}
        report["passed"] = not report["violations"]
        cursor = db.execute(
            """INSERT INTO runs(dataset, contract_hash, evaluated_at, passed, is_baseline, report)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (report["dataset"], report["contract_hash"], report["evaluated_at"],
             int(report["passed"]), int(baseline), json.dumps(report, allow_nan=False)),
        )
        report["run_id"] = cursor.lastrowid
        db.execute("UPDATE runs SET report=? WHERE id=?",
                   (json.dumps(report, allow_nan=False), cursor.lastrowid))
    return report


def recent(path, dataset, limit=20):
    if type(limit) is not int or limit < 1:
        raise ValueError("Limit must be positive")
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        rows = db.execute(
            """SELECT report FROM runs WHERE dataset=? ORDER BY id DESC LIMIT ?""",
            (dataset, limit),
        )
        return [json.loads(row[0]) for row in rows]


def main():
    parser = argparse.ArgumentParser(description="Inspect recorded data readiness runs")
    parser.add_argument("history")
    parser.add_argument("dataset")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    print(json.dumps(recent(args.history, args.dataset, args.limit), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
