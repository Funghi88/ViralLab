import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline import ContentItem, run_pipeline, stage_dedupe, stage_normalize, stage_sort_by_date_desc


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = PROJECT_ROOT / "tests" / "fixtures" / "pipeline_news_items.json"
        self.raw_items = json.loads(fixture.read_text(encoding="utf-8"))

    def test_normalize_drops_invalid_titles(self) -> None:
        normalized = stage_normalize(self.raw_items)
        self.assertEqual(len(normalized), 4)
        self.assertTrue(all(isinstance(item, ContentItem) for item in normalized))

    def test_dedupe_keeps_first_title_case_insensitive(self) -> None:
        normalized = stage_normalize(self.raw_items)
        deduped = stage_dedupe(normalized)
        titles = [item.title for item in deduped]
        self.assertEqual(len(deduped), 3)
        self.assertIn("AI Agents Are Growing Fast", titles)
        self.assertNotIn("ai agents are growing fast", titles)

    def test_sort_moves_newest_first_and_missing_dates_last(self) -> None:
        normalized = stage_normalize(self.raw_items)
        deduped = stage_dedupe(normalized)
        sorted_items = stage_sort_by_date_desc(deduped)
        titles = [item.title for item in sorted_items]
        self.assertEqual(titles[0], "Creator Economy Outlook")
        self.assertEqual(titles[-1], "No Date Item")

    def test_run_pipeline_returns_dicts(self) -> None:
        output = run_pipeline(self.raw_items)
        self.assertEqual(len(output), 3)
        self.assertTrue(all(isinstance(item, dict) for item in output))
        self.assertEqual(output[0]["title"], "Creator Economy Outlook")


if __name__ == "__main__":
    unittest.main()
