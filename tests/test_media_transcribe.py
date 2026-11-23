import json
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
    _douyin_cookie_file_runtime_status,
    _douyin_failure_diagnosis_block,
    _expand_short_url,
    _looks_like_douyin_url,
    _normalize_douyin_watch_url,
    _normalize_local_media_ref,
    _netscape_cookie_names_in_file,
    _pick_youtube_merged_file,
    _run_ytdlp_with_proxy_fallback,
    _try_transcribe_candidates,
    _yt_cookie_extras_nonempty,
    _yt_dlp_verbose,
    _find_yt_dlp_bin,
    download_youtube_media,
    download_youtube_audio,
    download_youtube_video,
    probe_youtube_formats,
)


class MediaTranscribeTests(unittest.TestCase):
    def test_ytdlp_retries_direct_when_configured_proxy_is_refused(self) -> None:
        failed = subprocess.CompletedProcess(
            ["yt-dlp"], 1, stdout="", stderr="ERROR: Unable to connect to proxy: Connection refused"
        )
        succeeded = subprocess.CompletedProcess(["yt-dlp"], 0, stdout="ok", stderr="")
        with patch.dict(
            os.environ,
            {
                "HTTP_PROXY": "http://127.0.0.1:18080",
                "HTTPS_PROXY": "http://127.0.0.1:18080",
                "VIRALLAB_MEDIA_DOWNLOAD_USE_ENV_PROXY": "1",
            },
            clear=False,
        ), patch("src.media_transcribe.subprocess.run", side_effect=[failed, succeeded]) as run:
            result = _run_ytdlp_with_proxy_fallback(["yt-dlp"], timeout_sec=10)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(run.call_count, 2)
        retry_env = run.call_args_list[1].kwargs["env"]
        self.assertNotIn("HTTP_PROXY", retry_env)
        self.assertNotIn("HTTPS_PROXY", retry_env)

    def test_yt_dlp_verbose_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "VIRALLAB_YTDLP_VERBOSE": "",
                "VIRALLAB_DEBUG_MEDIA": "",
                "VIRALLAB_DEBUG": "",
                "FLASK_DEBUG": "",
            },
            clear=False,
        ):
            self.assertFalse(_yt_dlp_verbose())
        with patch.dict(os.environ, {"VIRALLAB_YTDLP_VERBOSE": "1"}, clear=False):
            self.assertTrue(_yt_dlp_verbose())
        with patch.dict(os.environ, {"VIRALLAB_YTDLP_VERBOSE": "0"}, clear=False):
            self.assertFalse(_yt_dlp_verbose())
        with patch.dict(
            os.environ,
            {"VIRALLAB_YTDLP_VERBOSE": "", "VIRALLAB_DEBUG_MEDIA": "1"},
            clear=False,
        ):
            self.assertTrue(_yt_dlp_verbose())

    def test_normalize_local_media_ref_file_url_decodes_path(self) -> None:
        p = Path(__file__).resolve()
        normalized = _normalize_local_media_ref(f"file://{p.as_posix()}")
        self.assertEqual(normalized, str(p))

    def test_normalize_local_media_ref_strips_quotes(self) -> None:
        self.assertEqual(_normalize_local_media_ref('"/tmp/a b.mp4"'), "/tmp/a b.mp4")

    def test_looks_like_douyin_url(self) -> None:
        self.assertTrue(_looks_like_douyin_url("https://www.douyin.com/video/7632345202723769627"))
        self.assertTrue(_looks_like_douyin_url("https://v.douyin.com/foobar/"))
        self.assertFalse(_looks_like_douyin_url("https://www.bilibili.com/video/BV1xx411c7mD"))

    def test_normalize_douyin_jingxuan_modal_id_to_video(self) -> None:
        u = "https://www.douyin.com/jingxuan?modal_id=7627253494123099634"
        self.assertEqual(_normalize_douyin_watch_url(u), "https://www.douyin.com/video/7627253494123099634")

    def test_normalize_douyin_leaves_video_url(self) -> None:
        u = "https://www.douyin.com/video/7627253494123099634?extra=1"
        self.assertEqual(_normalize_douyin_watch_url(u), u)

    def test_yt_cookie_extras_skips_browser_when_cookie_file_configured(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File\n")
            f.write(".douyin.com\tTRUE\t/\tFALSE\t0\tsid\tfakevalue\n")
            fp = Path(f.name)
        try:
            with patch.dict(
                os.environ,
                {
                    "YTDLP_COOKIES_FILE": str(fp),
                    "VIRALLAB_YTDLP_USE_BROWSER_COOKIES": "",
                    "VIRALLAB_YTDLP_SKIP_BROWSER_COOKIES": "",
                },
                clear=False,
            ):
                ex = _yt_cookie_extras_nonempty("https://www.douyin.com/video/7632345202723769627")
            self.assertTrue(any(x and x[0] == "--cookies" for x in ex))
            self.assertFalse(any("--cookies-from-browser" in x for x in ex))
        finally:
            fp.unlink(missing_ok=True)

    def test_yt_cookie_extras_keeps_browser_for_non_douyin_even_with_cookie_file(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File\n")
            f.write(".douyin.com\tTRUE\t/\tFALSE\t0\tsid\tfakevalue\n")
            fp = Path(f.name)
        try:
            with patch.dict(
                os.environ,
                {
                    "YTDLP_COOKIES_FILE": str(fp),
                    "VIRALLAB_YTDLP_USE_BROWSER_COOKIES": "",
                    "VIRALLAB_YTDLP_SKIP_BROWSER_COOKIES": "",
                },
                clear=False,
            ):
                ex = _yt_cookie_extras_nonempty("https://www.bilibili.com/video/BV1234567890")
            self.assertTrue(any(x and x[0] == "--cookies" for x in ex))
            self.assertTrue(any("--cookies-from-browser" in x for x in ex))
        finally:
            fp.unlink(missing_ok=True)

    def test_yt_cookie_comments_only_still_uses_browser_for_douyin(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as f:
            f.write("# only comments — no tab-separated cookie rows\n# export from browser and paste here\n")
            fp = Path(f.name)
        try:
            with patch.dict(
                os.environ,
                {
                    "YTDLP_COOKIES_FILE": str(fp),
                    "VIRALLAB_YTDLP_USE_BROWSER_COOKIES": "",
                    "VIRALLAB_YTDLP_SKIP_BROWSER_COOKIES": "",
                },
                clear=False,
            ):
                ex = _yt_cookie_extras_nonempty("https://www.douyin.com/video/1")
            self.assertTrue(any("--cookies-from-browser" in x for x in ex))
        finally:
            fp.unlink(missing_ok=True)

    def test_yt_cookie_extras_includes_browser_without_cookie_file(self) -> None:
        with patch.dict(
            os.environ,
            {
                "YTDLP_COOKIES_FILE": "/nonexistent/virallab_no_cookie_file_12345.txt",
                "VIRALLAB_YTDLP_SKIP_BROWSER_COOKIES": "",
                "VIRALLAB_YTDLP_USE_BROWSER_COOKIES": "",
            },
            clear=False,
        ):
            ex = _yt_cookie_extras_nonempty("https://www.bilibili.com/video/BV1234567890")
        self.assertTrue(any("--cookies-from-browser" in x for x in ex))

    def test_douyin_without_cookie_file_single_browser_fragment(self) -> None:
        with patch("src.media_transcribe._yt_cookie_file_fragments", return_value=[]):
            with patch.dict(
                os.environ,
                {
                    "YTDLP_COOKIES_FILE": "",
                    "VIRALLAB_YTDLP_SKIP_BROWSER_COOKIES": "",
                    "VIRALLAB_YTDLP_USE_BROWSER_COOKIES": "",
                    "VIRALLAB_YTDLP_DOUYIN_WIDE_BROWSER": "",
                    "YTDLP_COOKIES_BROWSER": "chrome",
                    "YTDLP_COOKIES_PROFILE": "",
                },
                clear=False,
            ):
                ex = _yt_cookie_extras_nonempty("https://www.douyin.com/video/1")
        browserish = [x for x in ex if any(a == "--cookies-from-browser" for a in x)]
        self.assertEqual(len(browserish), 1)
        self.assertEqual(browserish[0], ["--cookies-from-browser", "chrome"])

    def test_douyin_wide_browser_env_restores_multi_probe(self) -> None:
        with patch("src.media_transcribe._yt_cookie_file_fragments", return_value=[]):
            with patch.dict(
                os.environ,
                {
                    "YTDLP_COOKIES_FILE": "",
                    "VIRALLAB_YTDLP_DOUYIN_WIDE_BROWSER": "1",
                    "VIRALLAB_YTDLP_SKIP_BROWSER_COOKIES": "",
                    "VIRALLAB_YTDLP_USE_BROWSER_COOKIES": "",
                },
                clear=False,
            ):
                ex = _yt_cookie_extras_nonempty("https://www.douyin.com/video/1")
        browserish = [x for x in ex if any(a == "--cookies-from-browser" for a in x)]
        self.assertGreaterEqual(len(browserish), 4)

    def test_find_yt_dlp_prefers_project_venv_over_path(self) -> None:
        venv_ytdlp = PROJECT_ROOT / ".venv" / "bin" / "yt-dlp"
        if not venv_ytdlp.is_file():
            self.skipTest("no .venv/bin/yt-dlp")
        with patch.dict(os.environ, {"VIRALLAB_YTDLP_BIN": ""}, clear=False):
            with patch("src.media_transcribe.shutil.which", return_value="/opt/homebrew/bin/yt-dlp"):
                picked = _find_yt_dlp_bin()
        self.assertEqual(Path(picked).resolve(), venv_ytdlp.resolve())

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

    def test_download_youtube_video_prefers_mp4_merge_first(self) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):  # noqa: ANN001
            calls.append(cmd)
            out_dir = Path(kwargs.get("cwd", "."))
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
            self.assertTrue(calls)
            first = calls[0]
            self.assertIn("--no-update", first)
            self.assertIn("--merge-output-format", first)
            self.assertEqual(first[first.index("--merge-output-format") + 1], "mp4")
            self.assertIn("-f", first)
            selector = first[first.index("-f") + 1]
            self.assertIn("bestvideo[ext=mp4]", selector)
            self.assertIn("bestaudio[ext=m4a]", selector)

    def test_download_youtube_video_retries_challenge_with_alt_clients(self) -> None:
        calls: list[list[str]] = []
        primary_extractor = "youtube:player_client=android,ios,tv;player_skip=webpage,configs"

        def fake_run(cmd, **kwargs):  # noqa: ANN001
            calls.append(cmd)
            out_dir = Path(kwargs.get("cwd", "."))
            extractor = ""
            if "--extractor-args" in cmd:
                extractor = cmd[cmd.index("--extractor-args") + 1]
            if extractor == primary_extractor:
                return subprocess.CompletedProcess(
                    cmd,
                    1,
                    stdout="",
                    stderr=(
                        "WARNING: [youtube] [jsc] Remote components challenge solver script "
                        "(deno) and NPM package (deno) were not found"
                    ),
                )
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
            self.assertGreaterEqual(len(calls), 2)
            self.assertTrue(any("--extractor-args" in c for c in calls))

    def test_download_youtube_video_rejects_non_youtube(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path, err = download_youtube_video("https://example.com/x", Path(td))
            self.assertIsNone(path)
            self.assertEqual(err, "not_youtube")

    def test_download_youtube_audio_success_writes_file(self) -> None:
        def fake_run(cmd, **kwargs):  # noqa: ANN001
            out_dir = Path(kwargs.get("cwd", "."))
            f = out_dir / "youtube_TESTVIDE012.m4a"
            f.write_bytes(b"audio")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            url = "https://www.youtube.com/watch?v=TESTVIDE012"
            with patch("src.media_transcribe.subprocess.run", side_effect=fake_run):
                with patch("src.media_transcribe._find_yt_dlp_bin", return_value="/bin/yt-dlp"):
                    path, err = download_youtube_audio(url, td_path)
            self.assertEqual(err, "")
            self.assertIsNotNone(path)
            assert path is not None
            self.assertEqual(path.suffix, ".m4a")
            self.assertEqual(path.read_bytes(), b"audio")

    def test_download_youtube_media_rejects_invalid_kind(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path, err = download_youtube_media(
                "https://www.youtube.com/watch?v=TESTVIDE012", Path(td), kind="documentary"
            )
            self.assertIsNone(path)
            self.assertEqual(err, "invalid_kind")

    def test_download_youtube_media_rejects_invalid_format_selector(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path, err = download_youtube_media(
                "https://www.youtube.com/watch?v=TESTVIDE012",
                Path(td),
                kind="video",
                format_selector="bad format selector",
            )
            self.assertIsNone(path)
            self.assertEqual(err, "invalid_format")

    def test_probe_youtube_formats_returns_video_and_audio_options(self) -> None:
        payload = {
            "title": "Test Video",
            "uploader": "Uploader",
            "duration": 123,
            "thumbnail": "https://img.example/thumb.jpg",
            "formats": [
                {
                    "format_id": "137",
                    "ext": "mp4",
                    "vcodec": "avc1",
                    "acodec": "none",
                    "height": 1080,
                    "fps": 30,
                    "filesize": 3_000_000,
                },
                {
                    "format_id": "22",
                    "ext": "mp4",
                    "vcodec": "avc1",
                    "acodec": "mp4a.40.2",
                    "height": 720,
                    "fps": 30,
                    "filesize": 2_000_000,
                },
                {
                    "format_id": "140",
                    "ext": "m4a",
                    "vcodec": "none",
                    "acodec": "mp4a.40.2",
                    "abr": 128,
                    "filesize": 400_000,
                },
            ],
        }
        cp = subprocess.CompletedProcess(
            ["yt-dlp", "--dump-single-json"], 0, stdout=json.dumps(payload), stderr=""
        )
        with patch("src.media_transcribe._find_yt_dlp_bin", return_value="/bin/yt-dlp"):
            with patch("src.media_transcribe.subprocess.run", return_value=cp):
                data, err = probe_youtube_formats("https://www.youtube.com/watch?v=TESTVIDE012")
        self.assertEqual(err, "")
        self.assertIsNotNone(data)
        assert data is not None
        self.assertEqual(data["title"], "Test Video")
        self.assertTrue(
            any(
                x["selector"] == "137+bestaudio[ext=m4a]/bestaudio/best"
                for x in data["video_options"]
            )
        )
        self.assertTrue(any(x["selector"] == "22" for x in data["video_options"]))
        self.assertTrue(any(x["selector"] == "140" for x in data["audio_options"]))
        self.assertEqual(data["video_options"][0]["format_id"], "best-mp4")

    def test_netscape_cookie_names_parses_sixth_field(self) -> None:
        with tempfile.NamedTemporaryFile(
            suffix=".txt", delete=False, mode="w", encoding="utf-8"
        ) as f:
            f.write("# meta\n")
            f.write(".douyin.com\tTRUE\t/\tFALSE\t0\ts_v_web_id\txxx\n")
            f.write(".douyin.com\tTRUE\t/\tFALSE\t0\tother\tfoo\n")
            fp = Path(f.name)
        try:
            names = _netscape_cookie_names_in_file(fp)
            self.assertEqual(names, {"s_v_web_id", "other"})
        finally:
            fp.unlink(missing_ok=True)

    def test_douyin_cookie_runtime_status_with_env_file(self) -> None:
        with tempfile.NamedTemporaryFile(
            suffix=".txt", delete=False, mode="w", encoding="utf-8"
        ) as f:
            f.write(".douyin.com\tTRUE\t/\tFALSE\t0\ts_v_web_id\tx\n")
            fp = Path(f.name)
        try:
            with patch.dict(os.environ, {"YTDLP_COOKIES_FILE": str(fp)}, clear=False):
                with patch("src.media_transcribe._repo_root", return_value=PROJECT_ROOT):
                    st = _douyin_cookie_file_runtime_status()
            self.assertEqual(st["n_cookie_files_with_netscape_rows"], 1)
            self.assertTrue(st["has_s_v_web_id_cookie_name"])
            self.assertEqual(st["distinct_cookie_name_count"], 1)
        finally:
            fp.unlink(missing_ok=True)

    def test_douyin_cookie_runtime_status_missing_s_v_web_id(self) -> None:
        with tempfile.NamedTemporaryFile(
            suffix=".txt", delete=False, mode="w", encoding="utf-8"
        ) as f:
            f.write(".douyin.com\tTRUE\t/\tFALSE\t0\tsession_other\tx\n")
            fp = Path(f.name)
        try:
            with patch.dict(os.environ, {"YTDLP_COOKIES_FILE": str(fp)}, clear=False):
                with patch("src.media_transcribe._repo_root", return_value=PROJECT_ROOT):
                    st = _douyin_cookie_file_runtime_status()
            self.assertGreaterEqual(st["n_cookie_files_with_netscape_rows"], 1)
            self.assertFalse(st["has_s_v_web_id_cookie_name"])
        finally:
            fp.unlink(missing_ok=True)

    def test_douyin_cookie_placeholder_flag(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "config" / "ytdlp_cookies.txt"
            cfg.parent.mkdir(parents=True)
            cfg.write_text("# comments only placeholder\n")
            with patch("src.media_transcribe._repo_root", return_value=root):
                with patch.dict(os.environ, {"YTDLP_COOKIES_FILE": ""}, clear=False):
                    st = _douyin_cookie_file_runtime_status()
            self.assertTrue(st["config_ytdlp_cookies_placeholder_only"])

    def test_douyin_failure_diagnosis_three_branches(self) -> None:
        b0 = _douyin_failure_diagnosis_block(
            {
                "n_cookie_files_with_netscape_rows": 0,
                "has_s_v_web_id_cookie_name": False,
                "config_ytdlp_cookies_placeholder_only": False,
            }
        )
        self.assertIn("--cookies", b0)

        b1 = _douyin_failure_diagnosis_block(
            {
                "n_cookie_files_with_netscape_rows": 1,
                "has_s_v_web_id_cookie_name": False,
                "config_ytdlp_cookies_placeholder_only": False,
            }
        )
        self.assertIn("s_v_web_id", b1)

        b2 = _douyin_failure_diagnosis_block(
            {
                "n_cookie_files_with_netscape_rows": 1,
                "has_s_v_web_id_cookie_name": True,
                "config_ytdlp_cookies_placeholder_only": False,
            }
        )
        self.assertIn("风控", b2)

        b_ph = _douyin_failure_diagnosis_block(
            {
                "n_cookie_files_with_netscape_rows": 0,
                "has_s_v_web_id_cookie_name": False,
                "config_ytdlp_cookies_placeholder_only": True,
            }
        )
        self.assertIn("只剩说明", b_ph)


if __name__ == "__main__":
    unittest.main()
