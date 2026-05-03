"""Tests for optional WhisperX pipeline and ASR config (no heavy deps required)."""
from __future__ import annotations

import os
import subprocess
import sys
from io import StringIO
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.transcription.config import (  # noqa: E402
    af_filter_for_preset,
    get_asr_engine,
    get_ffmpeg_af_preset,
    get_whisper_asr_options,
    get_whisper_hf_token,
    get_whisper_threads,
    get_whisper_vad_method,
    get_whisper_vad_options,
)
from src.transcription.preprocess import extract_audio_for_asr  # noqa: E402
from src.transcription.whisperx_runner import (  # noqa: E402
    TranscriptResult,
    _implicit_model_for_device,
    _prepare_vad_options_for_load,
    _stderr_asr_settings_enabled,
    _stderr_whisperx_failure,
    lang_to_whisper_code,
    resolve_whisper_model_name,
)
from src.media_transcribe import (  # noqa: E402
    TranscribeOutcome,
    transcribe_best_effort,
)


class TranscriptionConfigTests(unittest.TestCase):
    def test_lang_to_whisper_code(self) -> None:
        self.assertEqual(lang_to_whisper_code("zh"), "zh")
        self.assertEqual(lang_to_whisper_code("en"), "en")
        self.assertEqual(lang_to_whisper_code("fr"), "fr")
        self.assertEqual(lang_to_whisper_code("it"), "it")
        self.assertEqual(lang_to_whisper_code("de"), "en")
        self.assertIsNone(lang_to_whisper_code("auto"))

    def test_resolve_whisper_model_name_explicit_overrides(self) -> None:
        with patch.dict(os.environ, {"VIRALLAB_WHISPER_MODEL": "small"}, clear=False):
            self.assertEqual(resolve_whisper_model_name("cpu"), "small")
            self.assertEqual(resolve_whisper_model_name("cuda"), "small")

    def test_resolve_whisper_model_name_cpu_max_accuracy(self) -> None:
        with patch.dict(
            os.environ,
            {"VIRALLAB_WHISPER_MODEL": "", "VIRALLAB_WHISPER_MAX_ACCURACY": "1"},
            clear=False,
        ):
            self.assertEqual(resolve_whisper_model_name("cpu"), "large-v3")
        with patch.dict(
            os.environ,
            {"VIRALLAB_WHISPER_MODEL": "", "VIRALLAB_WHISPER_MAX_ACCURACY": "0"},
            clear=False,
        ):
            self.assertEqual(resolve_whisper_model_name("cpu"), "medium")

    def test_resolve_whisper_model_name_gpu_ignores_max_accuracy_flag(self) -> None:
        with patch.dict(
            os.environ,
            {"VIRALLAB_WHISPER_MODEL": "", "VIRALLAB_WHISPER_MAX_ACCURACY": "0"},
            clear=False,
        ):
            self.assertEqual(resolve_whisper_model_name("cuda"), "large-v3")
            self.assertEqual(resolve_whisper_model_name("mps"), "large-v3")

    def test_whisper_log_stderr_toggle(self) -> None:
        with patch.dict(os.environ, {"VIRALLAB_WHISPER_LOG": "0"}, clear=False):
            self.assertFalse(_stderr_asr_settings_enabled())
        with patch.dict(os.environ, {"VIRALLAB_WHISPER_LOG": "1"}, clear=False):
            self.assertTrue(_stderr_asr_settings_enabled())
        with patch.dict(os.environ, {"VIRALLAB_WHISPER_LOG": ""}, clear=False):
            self.assertTrue(_stderr_asr_settings_enabled())

    def test_stderr_whisperx_failure_truncates(self) -> None:
        long_msg = "x" * 400
        exc = RuntimeError(long_msg)
        buf = StringIO()
        with patch.dict(os.environ, {"VIRALLAB_WHISPER_LOG": "1"}, clear=False):
            with patch.object(sys, "stderr", buf):
                _stderr_whisperx_failure(exc, max_msg=80)
        out = buf.getvalue()
        self.assertIn("RuntimeError", out)
        self.assertNotIn(long_msg, out)

    def test_stderr_whisperx_failure_empty_message(self) -> None:
        buf = StringIO()
        with patch.dict(os.environ, {"VIRALLAB_WHISPER_LOG": "1"}, clear=False):
            with patch.object(sys, "stderr", buf):
                _stderr_whisperx_failure(RuntimeError())
        self.assertEqual(buf.getvalue().strip(), "[whisperx] error: RuntimeError")

    def test_implicit_model_cpu_respects_max_accuracy_env(self) -> None:
        with patch.dict(os.environ, {"VIRALLAB_WHISPER_MAX_ACCURACY": "1"}, clear=False):
            self.assertEqual(_implicit_model_for_device("cpu"), "large-v3")
        with patch.dict(os.environ, {"VIRALLAB_WHISPER_MAX_ACCURACY": "0"}, clear=False):
            self.assertEqual(_implicit_model_for_device("cpu"), "medium")

    def test_implicit_model_non_cpu_always_large_v3(self) -> None:
        with patch.dict(os.environ, {"VIRALLAB_WHISPER_MAX_ACCURACY": "0"}, clear=False):
            self.assertEqual(_implicit_model_for_device("cuda"), "large-v3")
            self.assertEqual(_implicit_model_for_device("mps"), "large-v3")

    def test_get_asr_engine_respects_env(self) -> None:
        with patch.dict(os.environ, {"VIRALLAB_ASR_ENGINE": "whisperx"}, clear=False):
            self.assertEqual(get_asr_engine(), "whisperx")
        with patch.dict(os.environ, {"VIRALLAB_ASR_ENGINE": "videocaptioner"}, clear=False):
            self.assertEqual(get_asr_engine(), "videocaptioner")

    def test_af_filter_speech_band_limit(self) -> None:
        self.assertIsNone(af_filter_for_preset("none"))
        f = af_filter_for_preset("speech_band_limit")
        self.assertIsNotNone(f)
        assert f is not None
        self.assertIn("highpass", f)
        self.assertIn("lowpass", f)

    def test_whisper_vad_and_asr_config(self) -> None:
        with patch.dict(
            os.environ,
            {
                "VIRALLAB_WHISPER_VAD_METHOD": "silero",
                "VIRALLAB_WHISPER_CHUNK_SIZE": "24",
                "VIRALLAB_WHISPER_VAD_ONSET": "0.45",
                "VIRALLAB_WHISPER_VAD_OFFSET": "0.35",
                "VIRALLAB_WHISPER_THREADS": "4",
                "VIRALLAB_WHISPER_ASR_OPTIONS_JSON": '{"beam_size": 7}',
            },
            clear=False,
        ):
            self.assertEqual(get_whisper_vad_method(), "silero")
            vo = get_whisper_vad_options()
            self.assertEqual(vo.get("chunk_size"), 24)
            self.assertAlmostEqual(vo["vad_onset"], 0.45)
            self.assertAlmostEqual(vo["vad_offset"], 0.35)
            self.assertEqual(get_whisper_threads(), 4)
            ao = get_whisper_asr_options()
            self.assertEqual(ao, {"beam_size": 7})
        self.assertIsNone(get_whisper_asr_options())

    def test_whisper_vad_method_invalid_falls_back(self) -> None:
        with patch.dict(os.environ, {"VIRALLAB_WHISPER_VAD_METHOD": "nope"}, clear=False):
            self.assertEqual(get_whisper_vad_method(), "pyannote")

    def test_prepare_vad_options_legacy_strips_chunk_size(self) -> None:
        class _Legacy:
            def load_model(self, whisper_arch, device, compute_type="float16", vad_options=None):
                pass

        wx = _Legacy()
        opts = {"chunk_size": 20, "vad_onset": 0.4, "vad_offset": 0.3}
        prepared = _prepare_vad_options_for_load(wx, opts)
        self.assertEqual(prepared, {"vad_onset": 0.4, "vad_offset": 0.3})

    def test_prepare_vad_options_new_keeps_chunk_size(self) -> None:
        class _New:
            def load_model(
                self,
                whisper_arch,
                device,
                vad_method="pyannote",
                vad_options=None,
            ):
                pass

        wx = _New()
        opts = {"chunk_size": 20, "vad_onset": 0.4, "vad_offset": 0.3}
        prepared = _prepare_vad_options_for_load(wx, opts)
        self.assertEqual(prepared, opts)

    def test_whisper_hf_token_prefers_virallab(self) -> None:
        with patch.dict(
            os.environ,
            {"VIRALLAB_HF_TOKEN": "aa", "HF_TOKEN": "bb"},
            clear=False,
        ):
            self.assertEqual(get_whisper_hf_token(), "aa")


class TranscriptionPipelineTests(unittest.TestCase):
    def test_transcribe_best_effort_uses_whisper_when_mocked(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"RIFF")
            p = f.name
        try:
            fake = TranscriptResult(text="hello world", language="en", segments=[{"start": 0, "end": 1, "text": "hello"}])
            with patch("src.media_transcribe.has_whisperx", return_value=True):
                with patch("src.media_transcribe.transcribe_audio_path", return_value=fake):
                    out = transcribe_best_effort(p, lang="en", engine="auto")
            self.assertEqual(out.text, "hello world")
            self.assertEqual(out.source, "WhisperX")
            self.assertIsNotNone(out.segments)
        finally:
            Path(p).unlink(missing_ok=True)

    def test_engine_videocaptioner_skips_whisperx(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"RIFF")
            p = f.name
        try:
            with patch("src.media_transcribe.transcribe_audio_path") as mock_wx:
                with patch(
                    "src.media_transcribe._transcribe_videocaptioner_pipeline",
                    return_value=TranscribeOutcome("from vc", "VideoCaptioner (ASR)", None),
                ) as mock_vc:
                    out = transcribe_best_effort(p, lang="en", engine="videocaptioner")
            mock_wx.assert_not_called()
            mock_vc.assert_called_once()
            self.assertEqual(out.text, "from vc")
        finally:
            Path(p).unlink(missing_ok=True)

    def test_transcribe_best_effort_zh_source_label(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"RIFF")
            p = f.name
        try:
            fake = TranscriptResult(text="你好", language="zh", segments=[])
            with patch("src.media_transcribe.has_whisperx", return_value=True):
                with patch("src.media_transcribe.transcribe_audio_path", return_value=fake):
                    out = transcribe_best_effort(p, lang="zh", engine="auto")
            self.assertEqual(out.source, "WhisperX（语音转文字）")
        finally:
            Path(p).unlink(missing_ok=True)

    def test_extract_audio_for_asr_none_preset_builds_cmd_without_af(self) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):  # noqa: ANN001
            calls.append(list(cmd))
            out_path = Path(cmd[-1])
            out_path.write_bytes(b"fake")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            media = td_path / "in.mp4"
            media.write_bytes(b"x")
            with patch("src.transcription.preprocess.subprocess.run", side_effect=fake_run):
                with patch("src.transcription.preprocess.find_ffmpeg", return_value="/bin/ffmpeg"):
                    out = extract_audio_for_asr(media, td_path, "none", "out.wav")
            self.assertIsNotNone(out)
            self.assertEqual(len(calls), 1)
            self.assertNotIn("-af", calls[0])


if __name__ == "__main__":
    unittest.main()
