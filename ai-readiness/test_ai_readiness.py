import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from ai_readiness import assess


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


if __name__ == '__main__':
    unittest.main()

