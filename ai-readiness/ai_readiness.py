"""CSV data contract gate for AI ingestion (Python 3.10+)."""
import argparse
import csv
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from readiness_contract import expected_columns, fingerprint, validate_contract
from readiness_history import record
from readiness_profile import Profile


def assess(path, contract, now=None):
    validate_contract(contract)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Evaluation time requires a timezone")
    required = contract.get('required', [])
    unique = contract.get('unique', [])
    numeric = contract.get('numeric', {})
    categories = contract.get('allowed_values', {})
    composite = [tuple(key) for key in contract.get('composite_keys', [])]
    null_limits = contract.get('max_null_fraction', {})
    freshness = contract.get('freshness')
    expected = expected_columns(contract)
    counts = {}
    seen = {column: set() for column in unique}
    seen_composite = {key: set() for key in composite}
    category_sets = {col: set(values) for col, values in categories.items()}
    blanks = {col: 0 for col in expected}
    profile = Profile(contract)
    rows = 0
    failed_rows = 0
    row_failed = False

    def fail(rule):
        nonlocal row_failed
        counts[rule] = counts.get(rule, 0) + 1
        row_failed = True

    with open(path, newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source, strict=True)
        headers = reader.fieldnames or []
        for col in sorted(expected - set(headers)):
            fail(f'missing_column:{col}')
        if not contract.get('allow_extra_columns', True):
            for col in sorted(set(headers) - set(contract['schema'])):
                fail(f'unexpected_column:{col}')
        if len(headers) != len(set(headers)):
            fail('duplicate_header')
        if not headers:
            fail('missing_header')
        for row in reader:
            row_failed = False
            rows += 1
            if None in row or any(value is None for value in row.values()):
                fail('malformed_row')
            for col in expected:
                if not (row.get(col) or '').strip():
                    blanks[col] += 1
            profile.observe(row)
            for col in required:
                if not (row.get(col) or '').strip():
                    fail(f'required:{col}')
            for col in unique:
                value = (row.get(col) or '').strip()
                if not value:
                    fail(f'unique_blank:{col}')
                elif value in seen[col]:
                    fail(f'duplicate:{col}')
                else:
                    seen[col].add(value)
            for key in composite:
                value = tuple((row.get(col) or '').strip() for col in key)
                label = json.dumps(key, separators=(',', ':'))
                if not all(value):
                    fail(f'composite_blank:{label}')
                elif value in seen_composite[key]:
                    fail(f'composite_duplicate:{label}')
                else:
                    seen_composite[key].add(value)
            for col, allowed in category_sets.items():
                if (row.get(col) or '').strip() not in allowed:
                    fail(f'allowed_values:{col}')
            for col, limits in numeric.items():
                try:
                    value = float(row.get(col) or '')
                    if not math.isfinite(value) or not limits.get('min', -math.inf) <= value <= limits.get('max', math.inf):
                        raise ValueError('out of range')
                except ValueError:
                    fail(f'numeric:{col}')
            if freshness:
                col = freshness['column']
                try:
                    stamp = datetime.fromisoformat((row.get(col) or '').replace('Z', '+00:00'))
                    if stamp.tzinfo is None:
                        raise ValueError('timezone required')
                    age = (now - stamp).total_seconds() / 3600
                    if not 0 <= age <= freshness['max_age_hours']:
                        fail(f'freshness:{col}')
                except ValueError:
                    fail(f'timestamp:{col}')
            failed_rows += int(row_failed)
    if rows < contract.get('min_rows', 1):
        fail('minimum_rows')
    if rows > contract.get('max_rows', math.inf):
        fail('maximum_rows')
    null_fraction = {col: count / rows if rows else 0.0 for col, count in blanks.items()}
    for col, maximum in null_limits.items():
        if null_fraction[col] > maximum:
            fail(f'null_fraction:{col}')
    return {
        'dataset': contract.get('dataset', 'default'),
        'contract_version': contract.get('version', '1'),
        'contract_hash': fingerprint(contract),
        'evaluated_at': now.astimezone(timezone.utc).isoformat(),
        'passed': not counts,
        'rows': rows,
        'failed_rows': failed_rows,
        'row_pass_rate': (rows - failed_rows) / rows if rows else None,
        'null_fraction': null_fraction,
        'violations': counts,
        'profile': profile.result(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv_file', type=Path)
    parser.add_argument('contract', type=Path)
    parser.add_argument('--history', type=Path, help='SQLite file for baseline and results')
    parser.add_argument('--promote-baseline', action='store_true',
                        help='Explicitly approve a new baseline if contract checks pass')
    parser.add_argument('--report', type=Path, help='Write JSON report to a new file')
    args = parser.parse_args()
    try:
        contract = json.loads(args.contract.read_text(encoding='utf-8'))
        validate_contract(contract)
        if (args.promote_baseline or contract.get('drift')) and args.history is None:
            raise ValueError("Drift detection and baseline promotion require --history")
        if args.history and args.history.resolve() in (args.csv_file.resolve(), args.contract.resolve()):
            raise ValueError("History must not be an input file")
        if args.history and args.report and args.history.resolve() == args.report.resolve():
            raise ValueError("History and report must be separate files")
        if args.report and args.report.exists():
            raise FileExistsError("Report already exists")
        report = assess(args.csv_file, contract)
        if args.history:
            report = record(args.history, report, contract.get('drift', {}), args.promote_baseline)
        if args.report:
            with args.report.open('x', encoding='utf-8') as destination:
                json.dump(report, destination, indent=2, sort_keys=True, allow_nan=False)
                destination.write('\n')
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError,
            csv.Error, sqlite3.Error) as exc:
        print(json.dumps({'passed': False, 'error_type': type(exc).__name__}))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
