import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("VIRALLAB_DISABLE_SCHEDULER", "1")
import server  # noqa: E402


class YoutubeDownloadApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = server.app.test_client()

    def test_youtube_download_defaults_to_video_kind(self) -> None:
        fake = Path("/tmp/youtube_TESTVIDE012.mp4")
        with patch("server.download_youtube_media", return_value=(fake, "")) as dl:
            r = self.client.post(
                "/api/youtube-download",
                json={"url": "https://www.youtube.com/watch?v=TESTVIDE012"},
            )
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["file"], fake.name)
        self.assertEqual(data["url"], f"/api/youtube-media/{fake.name}")
        dl.assert_called_once()
        args, kwargs = dl.call_args
        self.assertEqual(args[0], "https://www.youtube.com/watch?v=TESTVIDE012")
        self.assertEqual(args[1], server.OUTPUT)
        self.assertEqual(kwargs.get("kind"), "video")
        self.assertIsNone(kwargs.get("format_selector"))

    def test_youtube_download_supports_audio_kind(self) -> None:
        fake = Path("/tmp/youtube_TESTVIDE012.m4a")
        with patch("server.download_youtube_media", return_value=(fake, "")) as dl:
            r = self.client.post(
                "/api/youtube-download",
                json={
                    "url": "https://www.youtube.com/watch?v=TESTVIDE012",
                    "kind": "audio",
                },
            )
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["file"], fake.name)
        self.assertEqual(data["url"], f"/api/youtube-media/{fake.name}")
        dl.assert_called_once()
        _, kwargs = dl.call_args
        self.assertEqual(kwargs.get("kind"), "audio")
        self.assertIsNone(kwargs.get("format_selector"))

    def test_youtube_download_forwards_selected_format(self) -> None:
        fake = Path("/tmp/youtube_TESTVIDE012.mp4")
        with patch("server.download_youtube_media", return_value=(fake, "")) as dl:
            r = self.client.post(
                "/api/youtube-download",
                json={
                    "url": "https://www.youtube.com/watch?v=TESTVIDE012",
                    "kind": "video",
                    "format": "137+bestaudio/best",
                },
            )
        self.assertEqual(r.status_code, 200)
        dl.assert_called_once()
        _, kwargs = dl.call_args
        self.assertEqual(kwargs.get("kind"), "video")
        self.assertEqual(kwargs.get("format_selector"), "137+bestaudio/best")

    def test_youtube_download_rejects_invalid_kind(self) -> None:
        with patch("server.download_youtube_media") as dl:
            r = self.client.post(
                "/api/youtube-download",
                json={
                    "url": "https://www.youtube.com/watch?v=TESTVIDE012",
                    "kind": "text",
                },
            )
        self.assertEqual(r.status_code, 400)
        data = r.get_json()
        self.assertIn("Invalid download kind", data.get("error", ""))
        dl.assert_not_called()

    def test_youtube_download_rejects_invalid_format_selector(self) -> None:
        with patch("server.download_youtube_media", return_value=(None, "invalid_format")):
            r = self.client.post(
                "/api/youtube-download",
                json={
                    "url": "https://www.youtube.com/watch?v=TESTVIDE012",
                    "kind": "video",
                    "format": "bad format",
                },
            )
        self.assertEqual(r.status_code, 400)
        data = r.get_json()
        self.assertIn("Invalid format selector", data.get("error", ""))

    def test_youtube_download_requires_url(self) -> None:
        r = self.client.post("/api/youtube-download", json={"kind": "video"})
        self.assertEqual(r.status_code, 400)
        data = r.get_json()
        self.assertTrue(data.get("error"))

    def test_youtube_formats_endpoint_returns_probe_result(self) -> None:
        payload = {
            "video_id": "TESTVIDE012",
            "title": "Test Video",
            "thumbnail": "",
            "duration_sec": 100,
            "uploader": "Uploader",
            "video_options": [{"selector": "bestvideo+bestaudio/best", "label": "Best"}],
            "audio_options": [{"selector": "bestaudio", "label": "Best audio"}],
        }
        with patch("server.probe_youtube_formats", return_value=(payload, "")) as probe:
            r = self.client.post(
                "/api/youtube-formats",
                json={"url": "https://www.youtube.com/watch?v=TESTVIDE012"},
            )
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("video_id"), "TESTVIDE012")
        self.assertEqual(data.get("title"), "Test Video")
        probe.assert_called_once()

    def test_youtube_formats_requires_url(self) -> None:
        r = self.client.post("/api/youtube-formats", json={})
        self.assertEqual(r.status_code, 400)
        data = r.get_json()
        self.assertTrue(data.get("error"))


if __name__ == "__main__":
    unittest.main()
