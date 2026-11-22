"""Unit tests: python -m unittest discover -s tests -v"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))

from rag_retriever import retrieve
from rag_cli import load_documents, search_directory


class RetrieverTests(unittest.TestCase):
    def test_relevant_document_ranks_first(self):
        docs = ["snowflake cloud warehouse", "python data pipeline"]
        self.assertEqual(retrieve("snowflake warehouse", docs)[0][0], 0)

    def test_empty_inputs(self):
        self.assertEqual(retrieve("", ["something"]), [])
        self.assertEqual(retrieve("something", []), [])
        self.assertEqual(retrieve("something", [""]), [])

    def test_no_false_matches(self):
        self.assertEqual(retrieve("unicorn", ["data warehouse"]), [])

    def test_top_k(self):
        self.assertEqual(len(retrieve("data", ["data", "data science", "data lake"], 2)), 2)
        self.assertEqual(retrieve("data", ["data"], 0), [])

    def test_case_insensitive(self):
        self.assertEqual(retrieve("AI", ["ai models"])[0][0], 0)

    def test_directory_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "one.md").write_text("Snowflake data warehouse", encoding="utf-8")
            (root / "two.txt").write_text("Python automation scripts", encoding="utf-8")
            (root / "skip.json").write_text("Snowflake", encoding="utf-8")
            (root / "empty.md").write_text("  ", encoding="utf-8")
            paths, _ = load_documents(root)
            self.assertEqual(len(paths), 2)
            result = search_directory(root, "automation")
            self.assertEqual(result[0][0].name, "two.txt")

    def test_invalid_directory(self):
        with self.assertRaises(NotADirectoryError):
            load_documents(Path("/directory/that/does/not/exist"))


if __name__ == "__main__":
    unittest.main()
