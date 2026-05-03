import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.image_ocr import (
    extract_image_urls_from_html,
    host_is_blocked,
    looks_like_direct_image_url,
    normalize_page_url,
    ocr_pil_image,
    url_allowed_for_fetch,
)


class ImageOcrUtilTests(unittest.TestCase):
    def test_url_allowed_public(self) -> None:
        self.assertTrue(url_allowed_for_fetch("https://example.com/a.jpg"))
        self.assertFalse(url_allowed_for_fetch("file:///etc/passwd"))
        self.assertFalse(url_allowed_for_fetch("http://127.0.0.1/x"))

    def test_host_blocked_172_public_not_blocked(self) -> None:
        self.assertFalse(host_is_blocked("172.32.0.1"))
        self.assertTrue(host_is_blocked("172.16.0.1"))

    def test_normalize_protocol_relative(self) -> None:
        self.assertEqual(normalize_page_url("//a.com/x"), "https://a.com/x")

    def test_looks_like_direct_image(self) -> None:
        self.assertTrue(looks_like_direct_image_url("https://x.com/a.JPG?v=1"))
        self.assertFalse(looks_like_direct_image_url("https://mp.weixin.qq.com/s/abc"))

    def test_extract_image_urls_from_html(self) -> None:
        html = '<img data-src="//cdn/x.png"> <img src="/y.jpg">'
        base = "https://mp.weixin.qq.com/s/foo"
        got = extract_image_urls_from_html(html, base)
        self.assertIn("https://cdn/x.png", got)
        self.assertIn("https://mp.weixin.qq.com/y.jpg", got)

    def test_ocr_pil_parses_engine_output(self) -> None:
        class FakeEngine:
            def __call__(self, arr):  # noqa: ANN001
                return (
                    [
                        [[[0, 0], [1, 0], [1, 1], [0, 1]], "Line1", 0.91],
                        [[[0, 0], [1, 0], [1, 1], [0, 1]], "Line2", 0.88],
                    ],
                    0.0,
                )

        from PIL import Image

        im = Image.new("RGB", (10, 10), (255, 255, 255))
        with patch("src.image_ocr._get_ocr_engine", return_value=FakeEngine()):
            lines, text = ocr_pil_image(im)
        self.assertEqual(len(lines), 2)
        self.assertEqual(text, "Line1\nLine2")


if __name__ == "__main__":
    unittest.main()
