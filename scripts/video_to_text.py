#!/usr/bin/env python
"""Turn video/podcast/audio into markdown transcript.

Usage: python scripts/video_to_text.py <url_or_media_path>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.media_transcribe import transcribe_with_videocaptioner
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
        print("Usage: python scripts/video_to_text.py <url_or_media_path>")
        print("Example: python scripts/video_to_text.py https://www.youtube.com/watch?v=abc123")
        sys.exit(1)

    src = sys.argv[1]
    out_id = str(abs(hash(src)))[:12]
    transcript = ""
    vid = extract_youtube_id(src)
    if vid:
        transcript = get_transcript(vid)
        out_id = vid
    if not transcript:
        transcript, _ = transcribe_with_videocaptioner(src, lang="en")
    if not transcript:
        print("Could not fetch transcript. Install videocaptioner for ASR fallback.")
        sys.exit(1)

    score = score_berger(transcript)
    OUTPUT.mkdir(exist_ok=True)

    md = f"""# Video transcript

Source: {src}

## Berger score (script): {score['total']}/100
Magic words: {', '.join(score['magic_words_found']) or 'none'}

---

{transcript}
"""
    out_file = OUTPUT / f"transcript_{out_id}.md"
    out_file.write_text(md, encoding="utf-8")
    print(f"Saved to {out_file}")


if __name__ == "__main__":
    main()
