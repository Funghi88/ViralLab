#!/usr/bin/env python
"""Turn a YouTube video into markdown text. Usage: python scripts/video_to_text.py <youtube_url>"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.video_tools import extract_youtube_id, score_berger

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT = PROJECT_ROOT / "output"


def get_transcript(video_id: str) -> str:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        segments = YouTubeTranscriptApi.get_transcript(video_id)
        return " ".join(s["text"] for s in segments)
    except ImportError:
        return ""
    except Exception:
        return ""


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/video_to_text.py <youtube_url>")
        print("Example: python scripts/video_to_text.py https://www.youtube.com/watch?v=abc123")
        sys.exit(1)

    url = sys.argv[1]
    vid = extract_youtube_id(url)
    if not vid:
        print("Invalid YouTube URL")
        sys.exit(1)

    transcript = get_transcript(vid)
    if not transcript:
        print("Could not fetch transcript (video may not have captions)")
        sys.exit(1)

    score = score_berger(transcript)
    OUTPUT.mkdir(exist_ok=True)

    md = f"""# Video transcript

Source: {url}

## Berger score (script): {score['total']}/100
Magic words: {', '.join(score['magic_words_found']) or 'none'}

---

{transcript}
"""
    out_file = OUTPUT / f"transcript_{vid}.md"
    out_file.write_text(md, encoding="utf-8")
    print(f"Saved to {out_file}")


if __name__ == "__main__":
    main()
