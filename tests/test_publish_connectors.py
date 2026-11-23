"""Tests for 5-channel publish connectors, scheduled dispatch, and card handoff routes."""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import publish_connectors as pc  # noqa: E402
from src import publish_pipeline as pp  # noqa: E402


class PublishFormatterTests(unittest.TestCase):
    def test_blog_jekyll_frontmatter_matches_funghi88_schema(self) -> None:
        fname, md = pc.format_for_blog_jekyll(
            "AI Agents in 2026",
            "Why creators need integrated workflows.\n\nSecond paragraph.",
            category="Writing",
            date_str="2026-11-23",
        )
        self.assertEqual(fname, "2026-11-23-AI-Agents-in-2026.md")
        self.assertIn("layout: post\n", md)
        self.assertIn("title: 'AI Agents in 2026'\n", md)
        self.assertIn("date: 2026-11-23\n", md)
        self.assertIn("category: Writing\n", md)
        self.assertIn("excerpt:", md)

    def test_telegram_html_chunks_long_articles(self) -> None:
        long_body = "\n\n".join([f"Paragraph {i}: " + ("word " * 120) for i in range(10)])
        chunks = pc.format_for_telegram_html("Big Update", long_body)
        self.assertGreater(len(chunks), 1)
        for ch in chunks:
            self.assertLessEqual(len(ch), 3900)
        self.assertIn("<b>Big Update</b>", chunks[0])

    def test_wechat_html_inlines_styles(self) -> None:
        html_out = pc.format_for_wechat_html("测试标题", "## 核心结论\n\n这是一段正文。\n\n> 引用一段话")
        self.assertIn("border-left:4px solid #c9562b", html_out)
        self.assertIn("line-height:1.8", html_out)
        self.assertIn("<blockquote style=", html_out)

    def test_xiaohongshu_format_caps_title_and_adds_tags(self) -> None:
        res = pc.format_for_xiaohongshu(
            "这是一个非常非常长的小红书测试标题超过二十个字符",
            "AI 时代创作者如何打造个人品牌？\n\n第一，先给结论。\n\n第二，持续输出。",
        )
        self.assertLessEqual(len(res["title"]), 20)
        self.assertLessEqual(len(res["body"]), 1000)
        self.assertIn("#", res["body"])

    def test_x_thread_splits_long_content(self) -> None:
        body = " ".join([f"Sentence number {i} explains why behavioral science beats guesswork." for i in range(15)])
        tweets = pc.format_for_x_thread("ViralLab Thread", body)
        self.assertGreater(len(tweets), 1)
        for tw in tweets:
            self.assertLessEqual(len(tw), 280)
        self.assertTrue(tweets[0].endswith(f"(1/{len(tweets)})"))


class PublishConnectorDispatchTests(unittest.TestCase):
    def test_github_blog_dispatch_commits_to_posts_or_drafts(self) -> None:
        mock_get = MagicMock(status_code=404)
        mock_put = MagicMock(
            ok=True,
            status_code=201,
            json=lambda: {"content": {"html_url": "https://github.com/Funghi88/funghi88.github.io/blob/main/_drafts/test.md"}},
        )
        with patch.dict(
            os.environ,
            {"GITHUB_TOKEN": "ghp_test", "GITHUB_BLOG_REPO": "Funghi88/funghi88.github.io"},
            clear=False,
        ), patch("src.publish_connectors.requests.get", return_value=mock_get), patch(
            "src.publish_connectors.requests.put", return_value=mock_put
        ) as put_call:
            ok, msg, url = pc.publish_to_github_blog("Hello World", "Body text", draft=True)
        self.assertTrue(ok)
        self.assertIn("_drafts/", msg)
        self.assertIn("github.com/Funghi88/funghi88.github.io", url)
        sent_json = put_call.call_args.kwargs["json"]
        decoded = base64.b64decode(sent_json["content"]).decode("utf-8")
        self.assertIn("layout: post", decoded)

    def test_telegram_dispatch_sends_html(self) -> None:
        mock_post = MagicMock(
            ok=True,
            status_code=200,
            json=lambda: {"ok": True, "result": {"message_id": 42}},
        )
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "123:ABC", "TELEGRAM_CHAT_ID": "@virallab8"},
            clear=False,
        ), patch("src.publish_connectors.requests.post", return_value=mock_post):
            ok, msg, url = pc.publish_to_telegram("Daily Brief", "Top insight today.")
        self.assertTrue(ok)
        self.assertEqual(url, "https://t.me/virallab8/42")

    def test_x_dispatch_posts_thread(self) -> None:
        ids = iter(["1001", "1002", "1003"])
        def _fake_post(*args, **kwargs):
            tid = next(ids)
            return MagicMock(ok=True, status_code=201, json=lambda: {"data": {"id": tid}})

        with patch.dict(
            os.environ,
            {
                "X_API_KEY": "k",
                "X_API_SECRET": "s",
                "X_ACCESS_TOKEN": "t",
                "X_ACCESS_TOKEN_SECRET": "ts",
            },
            clear=False,
        ), patch("src.publish_connectors.requests.post", side_effect=_fake_post) as post_call:
            long_text = " ".join([f"Insight {i} about how creators grow steadily." for i in range(12)])
            ok, msg, url = pc.publish_to_x("Growth Notes", long_text)
        self.assertTrue(ok)
        self.assertEqual(url, "https://x.com/i/web/status/1001")
        self.assertGreaterEqual(post_call.call_count, 2)


class ScheduledPublishPipelineTests(unittest.TestCase):
    def test_due_items_dispatched_future_items_kept(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            with patch.object(pp, "OUTPUT", d), patch.object(pp, "QUEUE_FILE", d / "q.json"), patch.object(
                pp, "EVENTS_FILE", d / "e.jsonl"
            ), patch.object(pp, "dispatch_publish", return_value=(True, "ok", "https://funghi88.github.io/")):
                now = datetime.now().astimezone()
                past = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M")
                future = (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
                due_item = pp.queue_publish_item(
                    title="Due Post", content="Body due now", platform="blog", schedule_at=past
                )
                later_item = pp.queue_publish_item(
                    title="Future Post", content="Body later", platform="telegram", schedule_at=future
                )
                dispatched = pp.process_due_scheduled_items(now=now)
                self.assertEqual(len(dispatched), 1)
                self.assertEqual(dispatched[0]["id"], due_item["id"])
                items = {x["id"]: x for x in pp.list_publish_items()}
                self.assertEqual(items[due_item["id"]]["status"], "published")
                self.assertEqual(items[later_item["id"]]["status"], "queued")


class PublishAndHandoffRouteTests(unittest.TestCase):
    def test_publish_format_and_handoff_routes(self) -> None:
        os.environ["VIRALLAB_DISABLE_SCHEDULER"] = "1"
        import server

        client = server.app.test_client()
        for plat in pc.SUPPORTED_PLATFORMS:
            r = client.post(
                "/api/publish/format",
                json={"platform": plat, "title": "Test Title", "content": "Paragraph one.\n\nParagraph two."},
            )
            self.assertEqual(r.status_code, 200)
            self.assertTrue((r.get_json() or {}).get("ok"))

        r_pub = client.get("/publish")
        self.assertEqual(r_pub.status_code, 200)
        self.assertIn(b"funghi88.github.io", r_pub.data)
        self.assertIn(b"Telegram", r_pub.data)
        self.assertIn(b"WeChat", r_pub.data)
        self.assertIn(b"Xiaohongshu", r_pub.data)

        # Verify 1-click Rewrite & Publish buttons appear on /daily, /news, /longform
        for page in ("/daily", "/news", "/longform"):
            rp = client.get(page)
            self.assertEqual(rp.status_code, 200)
            self.assertIn(b"/api/handoff", rp.data, f"Missing handoff button on {page}")

        # Verify POST /api/handoff creates prefill file and redirects
        r_ho = client.post(
            "/api/handoff",
            data={"title": "Test Story", "snippet": "Key summary", "url": "https://example.com", "source": "BBC", "target": "publish"},
        )
        self.assertEqual(r_ho.status_code, 302)
        loc = r_ho.headers.get("Location", "")
        self.assertIn("/publish?prefill_file=handoff_", loc)
        # Clean up test handoff file
        fname = loc.split("prefill_file=")[1].split("&")[0]
        (server.OUTPUT / fname).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
