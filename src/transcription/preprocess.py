"""Extract and normalize audio for ASR (ffmpeg)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from src.transcription.config import af_filter_for_preset


def find_ffmpeg() -> str:
    p = shutil.which("ffmpeg")
    return p or ""


def extract_audio_for_asr(
    media_path: Path,
    work_dir: Path,
    af_preset: str,
    out_name: str = "extracted_audio.wav",
) -> Path | None:
    """16 kHz mono WAV; optional ``-af`` chain from preset."""
    ffmpeg_bin = find_ffmpeg()
    if not ffmpeg_bin:
        return None
    out = work_dir / out_name
    af = af_filter_for_preset(af_preset)
    cmd: list[str] = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(media_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
    ]
    if af:
        cmd += ["-af", af]
    cmd.append(str(out))
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if r.returncode == 0 and out.exists():
            return out
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None
