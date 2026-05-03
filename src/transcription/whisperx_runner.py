"""WhisperX transcription + alignment (optional dependency)."""
from __future__ import annotations

import gc
import inspect
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.transcription.config import (
    get_explicit_whisper_model,
    get_whisper_asr_options,
    get_whisper_batch_size,
    get_whisper_hf_token,
    get_whisper_threads,
    get_whisper_vad_method,
    get_whisper_vad_options,
    use_max_accuracy_whisper,
)
from src.transcription.format_transcript import format_transcript_text
from src.transcription.preprocess import extract_audio_for_asr

_logger = logging.getLogger(__name__)


@dataclass
class TranscriptResult:
    text: str
    language: str
    segments: list[dict] = field(default_factory=list)


def lang_to_whisper_code(lang: str) -> str | None:
    raw = (lang or "en").strip().lower()
    if raw == "auto":
        return None
    m = raw[:2]
    if m == "zh":
        return "zh"
    if m in ("fr", "it", "en"):
        return m
    return "en"


def _pick_device() -> str:
    d = (os.environ.get("VIRALLAB_WHISPER_DEVICE") or "auto").strip().lower()
    if d in ("cpu", "cuda", "mps"):
        return d
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def _implicit_model_for_device(device: str) -> str:
    """Pick Whisper model when ``VIRALLAB_WHISPER_MODEL`` is unset.

    GPU/MPS: always ``large-v3``. CPU: ``large-v3`` if
    ``use_max_accuracy_whisper()`` else ``medium`` (see ``VIRALLAB_WHISPER_MAX_ACCURACY``).
    """
    if device != "cpu":
        return "large-v3"
    return "large-v3" if use_max_accuracy_whisper() else "medium"


def resolve_whisper_model_name(device: str) -> str:
    """``VIRALLAB_WHISPER_MODEL`` if set, else :func:`_implicit_model_for_device` (CPU + max-accuracy aware)."""
    explicit = get_explicit_whisper_model()
    if explicit:
        return explicit
    return _implicit_model_for_device(device)


def _stderr_asr_settings_enabled() -> bool:
    """Unset or ``1``: print one ``[whisperx]`` line to stderr; ``0``/``false``/``no``/``off``: silent."""
    v = (os.environ.get("VIRALLAB_WHISPER_LOG") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _stderr_whisperx_failure(exc: BaseException, *, max_msg: int = 160) -> None:
    """One stderr line on ASR failure; message truncated, newlines flattened (no traceback)."""
    if not _stderr_asr_settings_enabled():
        return
    name = type(exc).__name__
    raw = str(exc).strip().replace("\n", " ")
    if not raw:
        print(f"[whisperx] error: {name}", file=sys.stderr)
        return
    if len(raw) > max_msg:
        raw = raw[: max_msg - 1] + "…"
    print(f"[whisperx] error: {name}: {raw}", file=sys.stderr)


def _compute_type(device: str) -> str:
    if device == "cuda":
        return "float16"
    if device == "mps":
        return "float16"
    return "int8"


def has_whisperx() -> bool:
    try:
        import whisperx  # noqa: F401

        return True
    except ImportError:
        return False


def _load_model_accepts_vad_method(whisperx: Any) -> bool:
    try:
        return "vad_method" in inspect.signature(whisperx.load_model).parameters
    except (TypeError, ValueError):
        return False


def _prepare_vad_options_for_load(
    whisperx: Any, vad_options: dict[str, float | int]
) -> dict[str, float | int]:
    """Legacy WhisperX passes ``vad_onset``/``vad_offset`` to pyannote only; ``chunk_size`` belongs on newer pipelines."""
    if _load_model_accepts_vad_method(whisperx):
        return dict(vad_options)
    return {k: v for k, v in vad_options.items() if k in ("vad_onset", "vad_offset")}


def _load_whisperx_model(
    whisperx: Any,
    *,
    model_name: str,
    device: str,
    compute_type: str,
    language: str | None,
    vad_method: str,
    vad_options: dict[str, float | int],
    asr_options: dict | None,
    threads: int | None,
    hf_token: str | None,
) -> Any:
    sig = inspect.signature(whisperx.load_model)
    params = sig.parameters
    prepared = _prepare_vad_options_for_load(whisperx, vad_options)
    kwargs: dict[str, Any] = {}
    if "whisper_arch" in params:
        kwargs["whisper_arch"] = model_name
    if "device" in params:
        kwargs["device"] = device
    if "compute_type" in params:
        kwargs["compute_type"] = compute_type
    if "language" in params and language is not None:
        kwargs["language"] = language
    if "task" in params:
        kwargs["task"] = "transcribe"
    if "vad_method" in params:
        kwargs["vad_method"] = vad_method
    if "vad_options" in params and prepared:
        kwargs["vad_options"] = prepared
    if "asr_options" in params and asr_options:
        kwargs["asr_options"] = asr_options
    if "threads" in params and threads is not None:
        kwargs["threads"] = threads
    if "use_auth_token" in params and hf_token:
        kwargs["use_auth_token"] = hf_token
    return whisperx.load_model(**kwargs)


def _transcribe_whisperx(model: Any, audio: Any, batch_size: int, chunk_size: int) -> Any:
    sig = inspect.signature(model.transcribe)
    kw: dict[str, Any] = {"batch_size": batch_size}
    if "chunk_size" in sig.parameters:
        kw["chunk_size"] = chunk_size
    return model.transcribe(audio, **kw)


def transcribe_audio_path(
    media_path: Path,
    work_dir: Path,
    lang: str,
    *,
    af_preset: str = "none",
) -> TranscriptResult | None:
    """Run WhisperX on media; writes normalized WAV when ffmpeg available."""
    if not has_whisperx():
        return None
    import whisperx

    media_path = Path(media_path)
    if not media_path.is_file():
        return None

    wav = extract_audio_for_asr(media_path, work_dir, af_preset, "whisperx_in.wav")
    audio_file = wav if wav else media_path

    device = _pick_device()
    model_name = resolve_whisper_model_name(device)
    compute_type = _compute_type(device)
    language = lang_to_whisper_code(lang)
    lang_label = language or "auto"
    batch_size = get_whisper_batch_size()
    vad_method = get_whisper_vad_method()
    vad_opts = get_whisper_vad_options()
    chunk_for_tx = int(vad_opts.get("chunk_size", 30))
    asr_opts = get_whisper_asr_options()
    threads = get_whisper_threads()
    hf_tok = get_whisper_hf_token()
    audio_label = audio_file.name
    _logger.info(
        "WhisperX ASR: model=%s device=%s compute=%s lang=%s batch=%s vad=%s vad_opts=%s "
        "af_preset=%s audio=%s",
        model_name,
        device,
        compute_type,
        lang_label,
        batch_size,
        vad_method,
        vad_opts,
        af_preset,
        audio_label,
    )
    if _stderr_asr_settings_enabled():
        print(
            "[whisperx] "
            f"model={model_name} device={device} compute={compute_type} "
            f"lang={lang_label} batch={batch_size} vad={vad_method} vad_opts={vad_opts!r} "
            f"af_preset={af_preset} audio={audio_label}",
            file=sys.stderr,
        )

    try:
        model = _load_whisperx_model(
            whisperx,
            model_name=model_name,
            device=device,
            compute_type=compute_type,
            language=language,
            vad_method=vad_method,
            vad_options=vad_opts,
            asr_options=asr_opts,
            threads=threads,
            hf_token=hf_tok,
        )
        audio = whisperx.load_audio(str(audio_file))
        result = _transcribe_whisperx(model, audio, batch_size, chunk_for_tx)
        lang_code = result.get("language") or language or "en"

        try:
            model_a, metadata = whisperx.load_align_model(
                language_code=lang_code,
                device=device,
            )
            result = whisperx.align(
                result["segments"],
                model_a,
                metadata,
                audio,
                device,
                return_char_alignments=False,
            )
        except Exception:
            pass

        segments_out: list[dict] = []
        parts: list[str] = []
        for seg in result.get("segments") or []:
            txt = (seg.get("text") or "").strip()
            if txt:
                parts.append(txt)
            seg_copy = {
                "start": seg.get("start"),
                "end": seg.get("end"),
                "text": txt,
            }
            if seg.get("words"):
                seg_copy["words"] = seg["words"]
            segments_out.append(seg_copy)

        fmt_lang = lang if lang.strip().lower() != "auto" else (lang_code or "en")
        full = format_transcript_text(" ".join(parts), fmt_lang)
        del model
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

        if not full:
            return None
        return TranscriptResult(text=full, language=lang_code, segments=segments_out)
    except Exception as exc:
        _logger.warning("WhisperX ASR failed: %s: %s", type(exc).__name__, exc)
        _stderr_whisperx_failure(exc)
        return None
