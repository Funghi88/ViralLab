#!/usr/bin/env python
"""ViralLab CLI. See README for commands."""
import os
import subprocess
import sys
from pathlib import Path

# Add src to path for standalone run
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Bypass proxy for DuckDuckGo (fixes "unsuccessful tunnel" in mainland China)
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy")


def _env_no_proxy():
    env = os.environ.copy()
    for v in _PROXY_VARS:
        env.pop(v, None)
    return env


def run(topic: str = "AI agents and LLMs"):
    """Run the news crew and save output to output/."""
    from dotenv import load_dotenv
    load_dotenv()
    from news_crew import create_news_crew

    crew = create_news_crew(topic)
    result = crew.kickoff()
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)
    out_file = output_dir / f"digest_{topic.replace(' ', '_')[:30]}.md"
    out_file.write_text(str(result), encoding="utf-8")
    print(f"\nSaved to {out_file}")
    return result


def run_search_only(topic: str):
    """Run search only (no LLM). Outputs to output/raw_{topic}.md for Cursor summarization."""
    script = Path(__file__).parent / "scripts" / "search_only.py"
    subprocess.run([sys.executable, str(script), topic], check=True, env=_env_no_proxy())


def run_daily_news():
    """Fetch today's top 3 news. Outputs to output/daily_news.md."""
    root = Path(__file__).parent
    script = root / "scripts" / "daily_news.py"
    env = _env_no_proxy()
    env["PYTHONPATH"] = str(root)
    subprocess.run([sys.executable, str(script)], check=True, env=env, cwd=root)


def run_videos(query: str, with_transcript: bool = False):
    """Fetch trending videos + Berger scores. Optional: --transcript for manuscript."""
    script = Path(__file__).parent / "scripts" / "video_trending.py"
    cmd = [sys.executable, str(script), query]
    if with_transcript:
        cmd.append("--transcript")
    subprocess.run(cmd, check=True, env=_env_no_proxy())


def run_video_to_text(url: str):
    """Turn YouTube video into markdown transcript."""
    script = Path(__file__).parent / "scripts" / "video_to_text.py"
    subprocess.run([sys.executable, str(script), url], check=True, env=_env_no_proxy())


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
