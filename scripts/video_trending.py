#!/usr/bin/env python
"""Fetch trending videos, optional transcripts, and Berger scores. No API keys."""
import sys
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.video_tools import fetch_viral_videos, score_berger, extract_youtube_id

PROJECT_ROOT = Path(__file__).parent.parent


def get_transcript(video_id: str) -> str:
    """Fetch transcript if youtube-transcript-api is installed."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        segments = YouTubeTranscriptApi.get_transcript(video_id)
        return " ".join(s["text"] for s in segments)
    except ImportError:
        return ""
    except Exception:
        return ""


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else "trending viral"
    fetch_transcripts = "--transcript" in sys.argv or "-t" in sys.argv

    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(exist_ok=True)

    print(f"Fetching viral videos: {query}...")
    videos = fetch_viral_videos(query, max_results=10)

    if not videos:
        print("No videos found.")
        return

    lines = [f"# Trending Videos: {query}\n"]
    for i, v in enumerate(videos, 1):
        title = v.get("title", "N/A")
        url = v.get("url", "")
        desc = v.get("description", "")[:200]
        views = v.get("views") or v.get("views_int") or "N/A"

        # Berger score on title + description
        text_to_score = f"{title} {desc}"
        score = score_berger(text_to_score)

        block = [
            f"## {i}. {title}",
            f"- URL: {url}",
            f"- Views: {views}",
            f"- **Berger score: {score['total']}/100**",
            f"- Magic words: {', '.join(score['magic_words_found']) or 'none'}",
            f"- {desc}",
        ]

        if fetch_transcripts:
            vid = extract_youtube_id(url)
            if vid:
                transcript = get_transcript(vid)
                if transcript:
                    t_score = score_berger(transcript)
                    block.append(f"- Transcript Berger: {t_score['total']}/100")
                    block.append(f"- Manuscript (excerpt): {transcript[:500]}...")
                    # Save full transcript as markdown for video-to-text
                    transcript_file = output_dir / f"transcript_{vid}.md"
                    transcript_file.write_text(
                        f"# {title}\n\nSource: {url}\n\nBerger score (script): {t_score['total']}/100\nMagic words: {', '.join(t_score['magic_words_found']) or 'none'}\n\n---\n\n{transcript}",
                        encoding="utf-8",
                    )

        lines.append("\n".join(block) + "\n")

    safe = query.replace(" ", "_")[:30]
    out_file = output_dir / f"videos_{safe}.md"
    out_file.write_text("\n".join(lines), encoding="utf-8")

    # Record run for lifecycle (rising/peaking/fading)
    try:
        from src.run_history import record_run
        record_run(f"videos_{safe}", videos[:10])
    except Exception:
        pass

    print(f"Saved to {out_file}")


if __name__ == "__main__":
    main()
