"""Regression tests for ViralLab macOS 27 rejuvenation fixes."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import llm_client, proxy_env  # noqa: E402
from src.output_cleanup import cleanup_youtube_fragments, _should_prune_file  # noqa: E402
from src.transcription.whisperx_runner import _pick_device  # noqa: E402


class ProxyEnvTests(unittest.TestCase):
    def setUp(self) -> None:
        proxy_env.clear_caches()

    def test_parse_scutil_socks_and_http(self) -> None:
        sample = """<dictionary> {
  HTTPEnable : 1
  HTTPPort : 7890
  HTTPProxy : 127.0.0.1
  SOCKSEnable : 1
  SOCKSPort : 51234
  SOCKSProxy : 127.0.0.1
}"""
        parsed = proxy_env.parse_scutil_proxy_output(sample)
        self.assertEqual(parsed["http"], "http://127.0.0.1:7890")
        self.assertEqual(parsed["https"], "http://127.0.0.1:7890")
        self.assertEqual(parsed["socks"], "socks5h://127.0.0.1:51234")

    def test_parse_scutil_floating_socks_only(self) -> None:
        sample = """<dictionary> {
  HTTPEnable : 0
  SOCKSEnable : 1
  SOCKSPort : 61422
  SOCKSProxy : 127.0.0.1
}"""
        parsed = proxy_env.parse_scutil_proxy_output(sample)
        self.assertEqual(parsed["http"], "")
        self.assertEqual(parsed["socks"], "socks5h://127.0.0.1:61422")

    def test_dead_env_proxy_falls_back_to_live_scutil_socks(self) -> None:
        env = {"HTTP_PROXY": "http://127.0.0.1:18080", "HTTPS_PROXY": "http://127.0.0.1:18080"}
        with patch.object(
            proxy_env,
            "is_proxy_url_reachable",
            side_effect=lambda u, timeout=0.25: "61422" in u,
        ), patch.object(
            proxy_env,
            "read_macos_system_proxy",
            return_value={"http": "", "https": "", "socks": "socks5h://127.0.0.1:61422", "raw": {}},
        ):
            active = proxy_env.resolve_active_proxy(env)
        self.assertEqual(active["mode"], "scutil_socks")
        self.assertEqual(active["https"], "socks5h://127.0.0.1:61422")

    def test_dead_env_proxy_and_tun_mode_returns_direct(self) -> None:
        env = {"HTTP_PROXY": "http://127.0.0.1:18080"}
        with patch.object(proxy_env, "is_proxy_url_reachable", return_value=False), patch.object(
            proxy_env,
            "read_macos_system_proxy",
            return_value={"http": "", "https": "", "socks": "", "raw": {}},
        ):
            clean_env = proxy_env.env_for_overseas(env)
        self.assertNotIn("HTTP_PROXY", clean_env)
        self.assertEqual(clean_env.get("VIRALLAB_NO_DOTENV_PROXY"), "1")


class CrawlerPathTests(unittest.TestCase):
    def test_all_platform_crawlers_point_to_repo_root(self) -> None:
        from tools.china_crawler.platforms import (
            douyin,
            instagram,
            shipinhao,
            tiktok,
            x_twitter,
            xhs,
            zhihu,
        )

        for mod in (douyin, xhs, zhihu, shipinhao, tiktok, x_twitter, instagram):
            self.assertEqual(mod._PROJECT_ROOT, PROJECT_ROOT, f"Wrong _PROJECT_ROOT in {mod.__name__}")


class OutputCleanupTests(unittest.TestCase):
    def test_youtube_files_are_ephemeral_and_fragments_cleaned(self) -> None:
        self.assertTrue(_should_prune_file("youtube_abc12345678.mp4"))
        self.assertFalse(_should_prune_file("daily_news.md"))
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "youtube_abc12345678.mp4").write_bytes(b"ok")
            (d / "youtube_abc12345678.f401.mp4").write_bytes(b"frag")
            (d / "youtube_abc12345678.f251.webm.part").write_bytes(b"part")
            removed = cleanup_youtube_fragments(d, "abc12345678")
            self.assertEqual(len(removed), 2)
            self.assertTrue((d / "youtube_abc12345678.mp4").exists())
            self.assertFalse((d / "youtube_abc12345678.f401.mp4").exists())


class WhisperDeviceTests(unittest.TestCase):
    def test_mps_maps_to_cpu_for_ctranslate2(self) -> None:
        with patch.dict(os.environ, {"VIRALLAB_WHISPER_DEVICE": "mps"}, clear=False):
            self.assertEqual(_pick_device(), "cpu")


class LlmFallbackTests(unittest.TestCase):
    def test_openai_failure_falls_back_to_anthropic(self) -> None:
        with patch.object(llm_client, "_load_env"), patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-test-openai", "ANTHROPIC_API_KEY": "sk-ant-test", "GEMINI_API_KEY": ""},
            clear=False,
        ), patch.object(llm_client, "_openai", side_effect=RuntimeError("quota")), patch.object(
            llm_client, "_anthropic", return_value="hello from claude"
        ) as m_ant:
            out = llm_client.call_llm("hi")
        self.assertEqual(out, "hello from claude")
        m_ant.assert_called_once()


class HotTrendingCacheGuardTests(unittest.TestCase):
    def test_empty_fetch_does_not_overwrite_valid_cache(self) -> None:
        from src import hot_trending

        with tempfile.TemporaryDirectory() as td:
            tmp_cache = Path(td) / "hot_trending.json"
            tmp_cache.write_text(
                json.dumps({"ts": 100.0, "topics_zh": ["AI 热点"], "topics_en": ["AI trend"]}),
                encoding="utf-8",
            )
            with patch.object(hot_trending, "CACHE_FILE", tmp_cache):
                saved = hot_trending.save_hot_trending_cache([], [])
            self.assertEqual(saved["topics_zh"], ["AI 热点"])
            self.assertEqual(saved["topics_en"], ["AI trend"])


if __name__ == "__main__":
    unittest.main()
