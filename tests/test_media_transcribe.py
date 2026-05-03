import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import requests

from src.media_transcribe import (
    _expand_short_url,
    _normalize_local_media_ref,
    _pick_youtube_merged_file,
    _try_transcribe_candidates,
    download_youtube_video,
)


class MediaTranscribeTests(unittest.TestCase):
    def test_normalize_local_media_ref_file_url_decodes_path(self) -> None:
        p = Path(__file__).resolve()
        normalized = _normalize_local_media_ref(f"file://{p.as_posix()}")
        self.assertEqual(normalized, str(p))

    def test_normalize_local_media_ref_strips_quotes(self) -> None:
        self.assertEqual(_normalize_local_media_ref('"/tmp/a b.mp4"'), "/tmp/a b.mp4")

    def test_expand_short_url_falls_back_when_proxy_fails(self) -> None:
        ok = MagicMock()
        ok.url = "https://www.xiaohongshu.com/discovery/item/abc"
        with patch(
            "src.media_transcribe.requests.get",
            side_effect=requests.exceptions.ProxyError(),
        ):
            with patch(
                "src.media_transcribe.requests.head",
                side_effect=requests.exceptions.ProxyError(),
            ):
                with patch(
                    "src.media_transcribe._session_get_trust_env_false",
                    return_value=ok,
                ):
                    out = _expand_short_url("http://xhslink.com/o/test")
        self.assertIn("xiaohongshu.com", out)

    def test_transcribe_candidates_try_fallback_engine(self) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):  # noqa: ANN001
            calls.append(cmd)
            if "--asr" in cmd and "jianying" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")
            return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="failed")

        with tempfile.TemporaryDirectory() as td:
            media = Path(td) / "audio.wav"
            media.write_bytes(b"fake")
            with patch("src.media_transcribe.subprocess.run", side_effect=fake_run):
                ok = _try_transcribe_candidates("videocaptioner", media, Path(td), {})

        self.assertTrue(ok)
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(any("--asr" in c and "bijian" in c for c in calls))
        self.assertTrue(any("--asr" in c and "jianying" in c for c in calls))

    def test_pick_youtube_merged_file_ignores_format_fragments(self) -> None:
        """Do not pick ``youtube_{id}.f251.webm``; prefer ``youtube_{id}.mp4``."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            vid = "ohNqsS0sh6w"
            (d / f"youtube_{vid}.f251.webm").write_bytes(b"a")
            (d / f"youtube_{vid}.mp4").write_bytes(b"b")
            picked = _pick_youtube_merged_file(d, vid)
            self.assertIsNotNone(picked)
            assert picked is not None
            self.assertEqual(picked.name, f"youtube_{vid}.mp4")

    def test_pick_youtube_merged_file_prefers_newer_container(self) -> None:
        """Stale .mp4 must not win over a freshly merged .mkv."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            vid = "abcdefghijk"
            mp4 = d / f"youtube_{vid}.mp4"
            mkv = d / f"youtube_{vid}.mkv"
            mp4.write_bytes(b"old")
            mkv.write_bytes(b"new")
            os.utime(mp4, (100, 100))
            os.utime(mkv, (200, 200))
            picked = _pick_youtube_merged_file(d, vid)
            self.assertIsNotNone(picked)
            assert picked is not None
            self.assertEqual(picked.suffix, ".mkv")

    def test_download_youtube_video_success_writes_file(self) -> None:
        def fake_run(cmd, **kwargs):  # noqa: ANN001
            out_dir = Path(kwargs.get("cwd", "."))
            # 11-char YouTube id; merged output only
            f = out_dir / "youtube_TESTVIDE012.mp4"
            f.write_bytes(b"x")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            url = "https://www.youtube.com/watch?v=TESTVIDE012"
            with patch("src.media_transcribe.subprocess.run", side_effect=fake_run):
                with patch("src.media_transcribe._find_yt_dlp_bin", return_value="/bin/yt-dlp"):
                    path, err = download_youtube_video(url, td_path)
            self.assertEqual(err, "")
            self.assertIsNotNone(path)
            assert path is not None
            self.assertTrue(path.name.startswith("youtube_"))
            self.assertEqual(path.read_bytes(), b"x")

    def test_download_youtube_video_rejects_non_youtube(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path, err = download_youtube_video("https://example.com/x", Path(td))
            self.assertIsNone(path)
            self.assertEqual(err, "not_youtube")


if __name__ == "__main__":
    unittest.main()
