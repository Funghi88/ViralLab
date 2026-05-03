import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.diagnostics import classify_error_message


class DiagnosticTests(unittest.TestCase):
    def test_rate_limit_classification(self) -> None:
        diag = classify_error_message("HTTP 429 too many requests", context="video")
        self.assertEqual(diag["code"], "rate_limited")
        self.assertEqual(diag["category"], "throttle")
        self.assertTrue(diag["retryable"])

    def test_timeout_classification(self) -> None:
        diag = classify_error_message("Request timed out after 25s", context="news")
        self.assertEqual(diag["code"], "timeout")
        self.assertEqual(diag["category"], "network")

    def test_context_specific_hint_for_china_video(self) -> None:
        diag = classify_error_message("unexpected backend failure", context="china_video")
        self.assertEqual(diag["code"], "unknown_error")
        self.assertIn("China source", str(diag["hint"]))


if __name__ == "__main__":
    unittest.main()
