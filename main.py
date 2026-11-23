#!/usr/bin/env python
"""ViralLab CLI. See README for commands."""
import os
import subprocess
import sys
from pathlib import Path

# Add project root & src to path for standalone run
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from src.proxy_env import env_for_overseas, load_dotenv_safe


def _env_for_subproc():
    env = env_for_overseas(os.environ.copy())
    env["PYTHONPATH"] = str(ROOT)
    return env


def run(topic: str = "AI agents and LLMs"):
    """Run the news crew and save output to output/."""
    load_dotenv_safe(ROOT / ".env")
    from news_crew import create_news_crew

    crew = create_news_crew(topic)
    result = crew.kickoff()
    output_dir = ROOT / "output"
    output_dir.mkdir(exist_ok=True)
    out_file = output_dir / f"digest_{topic.replace(' ', '_')[:30]}.md"
    out_file.write_text(str(result), encoding="utf-8")
    print(f"\nSaved to {out_file}")
    return result


def run_search_only(topic: str):
    """Run search only (no LLM). Outputs to output/raw_{topic}.md for Cursor summarization."""
    script = ROOT / "scripts" / "search_only.py"
    subprocess.run([sys.executable, str(script), topic], check=True, env=_env_for_subproc(), cwd=ROOT)


def run_daily_news():
    """Fetch today's top 3 news. Outputs to output/daily_news.md."""
    script = ROOT / "scripts" / "daily_news.py"
    subprocess.run([sys.executable, str(script)], check=True, env=_env_for_subproc(), cwd=ROOT)


def run_videos(query: str, with_transcript: bool = False):
    """Fetch trending videos + Berger scores. Optional: --transcript for manuscript."""
    script = ROOT / "scripts" / "video_trending.py"
    cmd = [sys.executable, str(script), query]
    if with_transcript:
        cmd.append("--transcript")
    subprocess.run(cmd, check=True, env=_env_for_subproc(), cwd=ROOT)


def run_video_to_text(url: str):
    """Turn YouTube video into markdown transcript."""
    script = ROOT / "scripts" / "video_to_text.py"
    subprocess.run([sys.executable, str(script), url], check=True, env=_env_for_subproc(), cwd=ROOT)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--search-only":
        topic = args[1] if len(args) > 1 else "AI agents"
        run_search_only(topic)
    elif args and args[0] == "--daily-news":
        run_daily_news()
    elif args and args[0] == "--videos":
        query = args[1] if len(args) > 1 else "trending viral"
        run_videos(query, with_transcript="--transcript" in args or "-t" in args)
    elif args and args[0] in ("--video-to-text", "--v2t"):
        url = args[1] if len(args) > 1 else ""
        if not url:
            print("Usage: python main.py --video-to-text <youtube_url>")
            sys.exit(1)
        run_video_to_text(url)
    else:
        topic = args[0] if args else "AI agents and LLMs"
        run(topic)
