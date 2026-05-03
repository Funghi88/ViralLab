"""Tests for src.video_tools helpers."""
from __future__ import annotations

import unittest

from src.video_tools import extract_youtube_id


class ExtractYoutubeIdTests(unittest.TestCase):
    def test_standard_watch_url(self) -> None:
        self.assertEqual(
            extract_youtube_id("https://www.youtube.com/watch?v=jNQXAC9IVRw"),
            "jNQXAC9IVRw",
        )

    def test_watch_url_with_si_before_v(self) -> None:
        """Mobile/app shares often put si= before v=."""
        self.assertEqual(
            extract_youtube_id(
                "https://www.youtube.com/watch?si=abcdefg&v=jNQXAC9IVRw"
            ),
            "jNQXAC9IVRw",
        )

    def test_youtu_be(self) -> None:
        self.assertEqual(
            extract_youtube_id("https://youtu.be/jNQXAC9IVRw?t=12"),
            "jNQXAC9IVRw",
        )


if __name__ == "__main__":
    unittest.main()
