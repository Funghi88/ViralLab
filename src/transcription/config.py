"""Environment-driven ASR and ffmpeg preprocessing settings."""
from __future__ import annotations

import json
import os

# VIRALLAB_ASR_ENGINE: auto | whisperx | videocaptioner
# auto: try WhisperX when importable, else VideoCaptioner
# whisperx: prefer WhisperX, fall back to VideoCaptioner on failure
# videocaptioner: VideoCaptioner only

# VIRALLAB_WHISPER_MAX_ACCURACY: 1 (default) with VIRALLAB_WHISPER_MODEL unset uses large-v3 on CPU too; 0 uses medium on CPU only.
# VIRALLAB_WHISPER_MODEL: e.g. large-v3, medium (always overrides the above when set)

# VIRALLAB_WHISPER_DEVICE: auto | cpu | cuda | mps

# VIRALLAB_FFMPEG_AF_PRESET: none | speech_band_limit
#
# WhisperX VAD (newer whisperx: pyannote | silero; legacy builds ignore VAD_METHOD)
# VIRALLAB_WHISPER_VAD_METHOD=pyannote
# VIRALLAB_WHISPER_CHUNK_SIZE=30
# VIRALLAB_WHISPER_VAD_ONSET=0.5
# VIRALLAB_WHISPER_VAD_OFFSET=0.363
# VIRALLAB_WHISPER_THREADS=4
# VIRALLAB_WHISPER_ASR_OPTIONS_JSON={"beam_size":5}   # merges into faster-whisper options
# VIRALLAB_HF_TOKEN / HF_TOKEN — pyannote gated models when whisperx passes use_auth_token


def get_asr_engine() -> str:
    v = (os.environ.get("VIRALLAB_ASR_ENGINE") or "auto").strip().lower()
    if v in ("auto", "whisperx", "videocaptioner"):
        return v
    return "auto"


def get_ffmpeg_af_preset() -> str:
    v = (os.environ.get("VIRALLAB_FFMPEG_AF_PRESET") or "none").strip().lower()
    if v in ("none", "speech_band_limit"):
        return v
    return "none"


def af_filter_for_preset(preset: str) -> str | None:
    if preset == "none":
        return None
    if preset == "speech_band_limit":
        return "highpass=f=200,lowpass=f=6000"
    return None


def get_whisper_batch_size() -> int:
    raw = (os.environ.get("VIRALLAB_WHISPER_BATCH_SIZE") or "").strip()
    if raw.isdigit():
        return max(1, min(64, int(raw)))
    return 8


def get_explicit_whisper_model() -> str | None:
    m = (os.environ.get("VIRALLAB_WHISPER_MODEL") or "").strip()
    return m if m else None


def use_max_accuracy_whisper() -> bool:
    """When True (default), prefer large-v3 on CPU too; set VIRALLAB_WHISPER_MAX_ACCURACY=0 for medium on CPU only."""
    v = (os.environ.get("VIRALLAB_WHISPER_MAX_ACCURACY") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def get_whisper_vad_method() -> str:
    """``pyannote`` or ``silero`` (WhisperX 3.2+). Invalid values fall back to ``pyannote``."""
    v = (os.environ.get("VIRALLAB_WHISPER_VAD_METHOD") or "pyannote").strip().lower()
    if v in ("pyannote", "silero"):
        return v
    return "pyannote"


def get_whisper_vad_options() -> dict[str, float | int]:
    """Keys passed to WhisperX ``vad_options`` (chunk_size, vad_onset, vad_offset). Omitted keys use library defaults."""
    out: dict[str, float | int] = {}
    raw = (os.environ.get("VIRALLAB_WHISPER_CHUNK_SIZE") or "").strip()
    if raw.isdigit():
        out["chunk_size"] = max(1, min(120, int(raw)))
    raw = (os.environ.get("VIRALLAB_WHISPER_VAD_ONSET") or "").strip()
    if raw:
        try:
            out["vad_onset"] = float(raw)
        except ValueError:
            pass
    raw = (os.environ.get("VIRALLAB_WHISPER_VAD_OFFSET") or "").strip()
    if raw:
        try:
            out["vad_offset"] = float(raw)
        except ValueError:
            pass
    return out


def get_whisper_threads() -> int | None:
    raw = (os.environ.get("VIRALLAB_WHISPER_THREADS") or "").strip()
    if raw.isdigit():
        return max(1, min(32, int(raw)))
    return None


def get_whisper_asr_options() -> dict | None:
    """Optional JSON object merged into faster-whisper ``asr_options`` when supported."""
    raw = (os.environ.get("VIRALLAB_WHISPER_ASR_OPTIONS_JSON") or "").strip()
    if not raw:
        return None
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return d if isinstance(d, dict) else None


def get_whisper_hf_token() -> str | None:
    """HF token for gated models (pyannote). Prefer project-specific env."""
    for k in ("VIRALLAB_HF_TOKEN", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        t = (os.environ.get(k) or "").strip()
        if t:
            return t
    return None
