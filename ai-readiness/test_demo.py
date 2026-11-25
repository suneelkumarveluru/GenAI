import tempfile
import unittest
from pathlib import Path
from demo import demo
from readiness_dashboard import render


class DemoTests(unittest.TestCase):
    def test_three_batch_demo(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "demo"
            runs = demo(output)
            self.assertEqual([run["passed"] for run in runs], [False, False, True])
            self.assertTrue(any(key.startswith("drift:") for key in runs[1]["violations"]))
            self.assertIn('numeric:amount', runs[0]["violations"])
            self.assertTrue((output / "dashboard.html").exists())
            self.assertTrue((output / "baseline.json").exists())
            self.assertIn("retail_orders", (output / "dashboard.html").read_text(encoding="utf-8"))

    def test_html_metadata_escaped(self):
        self.assertNotIn("<script>", render([], "<script>"))
        self.assertIn("&lt;script&gt;", render([], "<script>"))
