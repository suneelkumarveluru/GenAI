"""CSV data contract gate for AI ingestion (Python 3.10+)."""
import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path


def assess(path, contract, now=None):
    now = now or datetime.now(timezone.utc)
    required = contract.get('required', [])
    unique = contract.get('unique', [])
    numeric = contract.get('numeric', {})
    freshness = contract.get('freshness')
    expected = set(required) | set(unique) | set(numeric)
    if freshness:
        expected.add(freshness['column'])
    counts = {}
    seen = {column: set() for column in unique}
    rows = 0

    def fail(rule):
        counts[rule] = counts.get(rule, 0) + 1

    with open(path, newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source)
        headers = reader.fieldnames or []
        for col in sorted(expected - set(headers)):
            fail(f'missing_column:{col}')
        if len(headers) != len(set(headers)):
            fail('duplicate_header')
        if not headers:
            fail('missing_header')
        for row in reader:
            rows += 1
            if None in row or any(value is None for value in row.values()):
                fail('malformed_row')
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
    if rows < contract.get('min_rows', 1):
        fail('minimum_rows')
    return {'passed': not counts, 'rows': rows, 'violations': counts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv_file', type=Path)
    parser.add_argument('contract', type=Path)
    args = parser.parse_args()
    try:
        contract = json.loads(args.contract.read_text(encoding='utf-8'))
        report = assess(args.csv_file, contract)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, csv.Error) as exc:
        print(json.dumps({'passed': False, 'error_type': type(exc).__name__}))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

