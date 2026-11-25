import tempfile
import unittest
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from ai_readiness import assess
from readiness_contract import validate_contract
from readiness_history import record, recent
from readiness_profile import distance


class ReadinessTests(unittest.TestCase):
    def check(self, content, contract):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data.csv'
            path.write_text(content, encoding='utf-8')
            return assess(path, contract, datetime(2026, 11, 25, tzinfo=timezone.utc))

    def test_valid(self):
        self.assertTrue(self.check('id,amount\n1,5\n2,10\n', {'required': ['id'], 'unique': ['id'], 'numeric': {'amount': {'min': 0}}})['passed'])

    def test_duplicate_and_nonfinite(self):
        report = self.check('id,amount\n1,nan\n1,-2\n', {'unique': ['id'], 'numeric': {'amount': {'min': 0}}})
        self.assertEqual(report['violations'], {'numeric:amount': 2, 'duplicate:id': 1})

    def test_missing_and_empty(self):
        report = self.check('id\n', {'required': ['amount']})
        self.assertEqual(report['violations'], {'missing_column:amount': 1, 'minimum_rows': 1})

    def test_freshness(self):
        report = self.check('ts\n2026-11-24T23:00:00Z\n2026-11-20T00:00:00Z\n2026-11-25T00:00:00\n', {'freshness': {'column': 'ts', 'max_age_hours': 24}})
        self.assertEqual(report['violations'], {'freshness:ts': 1, 'timestamp:ts': 1})

    def test_strict_schema(self):
        report = self.check('id,extra\n1,2\n', {
            'schema': ['id', 'amount'], 'allow_extra_columns': False,
        })
        self.assertEqual(report['violations'], {'missing_column:amount': 1, 'unexpected_column:extra': 1})

    def test_composite_and_category(self):
        report = self.check('order,line,status\n1,1,PAID\n1,1,MISSING\n1,2,OPEN\n', {
            'composite_keys': [['order', 'line']], 'allowed_values': {'status': ['OPEN', 'PAID']},
        })
        self.assertEqual(report['violations'], {'composite_duplicate:["order","line"]': 1,
                                              'allowed_values:status': 1})
        self.assertEqual(report['failed_rows'], 1)
        self.assertAlmostEqual(report['row_pass_rate'], 2 / 3)
        self.assertEqual(report['profile']['categorical']['status'], [1, 1, 1, 0])

    def test_aggregate_rules(self):
        report = self.check('id,note\n1,\n2,ok\n', {'max_rows': 1, 'max_null_fraction': {'note': 0.25}})
        self.assertEqual(report['violations'], {'maximum_rows': 1, 'null_fraction:note': 1})
        self.assertEqual(report['null_fraction']['note'], 0.5)
        self.assertEqual(report['failed_rows'], 0)

    def test_malformed_rows_and_duplicates(self):
        report = self.check('id,id\n1,2,3\n4\n', {'required': ['id']})
        self.assertEqual(report['violations']['duplicate_header'], 1)
        self.assertEqual(report['violations']['malformed_row'], 2)
        self.assertEqual(report['failed_rows'], 2)

    def test_histograms_include_invalid_and_blank(self):
        report = self.check('amount\n0\n10\n20\nnan\n""\n', {'histograms': {'amount': [10, 20]}})
        self.assertEqual(report['profile']['numeric']['amount'], [1, 1, 1, 1, 1])
        self.assertEqual(distance([3, 0], [0, 2]), 1.0)
        self.assertEqual(distance([1, 2], [2, 4]), 0.0)

    def test_contract_validation(self):
        invalid = [
            {'typo': 1}, {'numeric': {'a': {'min': 2, 'max': 1}}},
            {'min_rows': True}, {'required': ['x', 'x']},
            {'schema': ['x'], 'unique': ['y']},
            {'histograms': {'x': [10, 5]}},
            {'max_null_fraction': {'x': -0.1}},
            {'drift': {'max_distribution_distance': 0.1}},
        ]
        for contract in invalid:
            with self.subTest(contract=contract), self.assertRaises(ValueError):
                validate_contract(contract)

    def test_history_fixed_baseline_and_promotion(self):
        contract = {'dataset': 'sales', 'numeric': {'amount': {'min': 0}},
                    'histograms': {'amount': [100]},
                    'drift': {'max_distribution_distance': 0.4, 'max_row_change': 0.25}}
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'runs.sqlite'
            first = record(db, self.check('amount\n10\n20\n', contract), contract['drift'])
            self.assertEqual(first['drift']['status'], 'baseline_created')
            failed = record(db, self.check('amount\n1000\n', contract), contract['drift'])
            self.assertEqual(failed['violations'], {'drift:row_count': 1, 'drift:numeric:amount': 1})
            retry = record(db, self.check('amount\n10\n20\n', contract), contract['drift'])
            self.assertEqual(retry['drift']['baseline_id'], first['run_id'])
            promoted = record(db, self.check('amount\n1000\n', contract), contract['drift'], True)
            self.assertTrue(promoted['passed'])
            self.assertEqual(promoted['drift']['status'], 'baseline_promoted')
            self.assertIn('drift:row_count', promoted['drift']['overridden_violations'])
            bad = record(db, self.check('amount\n-1\n', contract), contract['drift'], True)
            self.assertFalse(bad['passed'])
            self.assertEqual(bad['drift']['baseline_id'], promoted['run_id'])
            self.assertEqual(len(recent(db, 'sales')), 5)

    def test_contract_versions_isolate_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'runs.sqlite'
            for version in ('1', '2'):
                report = record(db, self.check('id\n1\n', {'version': version}), {})
                self.assertEqual(report['drift']['status'], 'baseline_created')
            self.assertEqual(len(recent(db, 'default')), 2)

    def test_cli_reports_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            csv_file, contract_file = path / 'batch.csv', path / 'contract.json'
            report_file = path / 'report.json'
            contract_file.write_text(json.dumps({'required': ['id'], 'unique': ['id']}))
            csv_file.write_text('id\na\na\n')
            command = [sys.executable, str(Path(__file__).with_name('ai_readiness.py')),
                       str(csv_file), str(contract_file)]
            run = subprocess.run(command + ['--report', str(report_file)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 1)
            self.assertEqual(json.loads(report_file.read_text())['violations'], {'duplicate:id': 1})
            self.assertNotIn('a\na', run.stdout)
            self.assertEqual(subprocess.run(command + ['--report', str(report_file)],
                                            capture_output=True).returncode, 2)
            csv_file.write_text('id\na\nb\n')
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
            contract_file.write_text('{"unknown_rule": 1}')
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)

    def test_cli_requires_history_for_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            csv_file, contract_file = path / 'batch.csv', path / 'contract.json'
            csv_file.write_text('amount\n1\n')
            contract_file.write_text(json.dumps({'drift': {'max_row_change': 0.2}}))
            command = [sys.executable, str(Path(__file__).with_name('ai_readiness.py')),
                       str(csv_file), str(contract_file)]
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)
            self.assertEqual(subprocess.run(command + ['--history', str(path / 'runs.sqlite')],
                                            capture_output=True).returncode, 0)


if __name__ == '__main__':
    unittest.main()
