import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.minto_pyramid import minto_to_markdown, structure_minto


class MintoPyramidTests(unittest.TestCase):
    def test_structure_produces_strict_sections_for_zh_transcript(self) -> None:
        transcript = (
            "AI 让执行效率提升很多 但也让同质化更快出现\n"
            "很多设计师会焦虑 因为原来的经验不再稳定\n"
            "真正有价值的是判断力 业务理解 和内容框架能力\n"
            "我们需要把结论前置 用三个要点表达 再配上证据\n"
            "这样更容易复用到短视频 图文 和长文"
        )
        minto = structure_minto(transcript, lang="zh")
        self.assertTrue((minto.get("conclusion") or "").strip())
        self.assertGreaterEqual(len(minto.get("key_points") or []), 3)
        self.assertEqual(minto.get("logic_order"), "因果")

        md = minto_to_markdown(minto, lang="zh")
        self.assertIn("## 结论（先给答案）", md)
        self.assertIn("## 要点（分组）", md)
        self.assertIn("## 支撑论据", md)

    def test_structure_keeps_working_for_short_text(self) -> None:
        transcript = "AI changed content workflows quickly, and creators now need clearer structure and stronger judgment."
        minto = structure_minto(transcript, lang="en")
        self.assertTrue((minto.get("conclusion") or "").strip())
        self.assertGreaterEqual(len(minto.get("key_points") or []), 3)
        self.assertEqual(minto.get("logic_order"), "Cause-Effect")


if __name__ == "__main__":
    unittest.main()
