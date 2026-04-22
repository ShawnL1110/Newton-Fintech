"""Local transcription via faster-whisper.

Runs a CTranslate2-optimized Whisper model on CPU (or Metal on Apple
Silicon via `compute_type="int8"`), producing text without making any
API calls. Intended for the "mixed" engine where transcription is
local but translation still goes through OpenAI.

First use downloads the model (~470MB for `small`) to the user's
HuggingFace cache. Subsequent runs load from disk in a few seconds.
"""

from __future__ import annotations

import sys


class LocalWhisperTranscriber:
    """Wraps faster-whisper's WhisperModel for single-segment transcription."""

    def __init__(self, model_size="small", language=None, compute_type="int8"):
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise RuntimeError(
                "faster-whisper 未安装, 请运行:\n"
                "  pip install faster-whisper\n"
                f"原始错误: {e}"
            )

        print(f"[local-whisper] 加载模型 {model_size} (compute={compute_type})…",
              file=sys.stderr, flush=True)
        self._model = WhisperModel(
            model_size,
            device="cpu",
            compute_type=compute_type,
        )
        self.language = language  # None = auto-detect

    def transcribe(self, audio_float32, samplerate):
        """Run Whisper on a mono float32 numpy array. Returns stripped text.

        faster-whisper expects 16kHz mono; it'll resample internally if we
        pass the samplerate explicitly. We disable VAD here because our
        Segmenter already bounded this segment by silence.
        """
        # Resample to 16kHz if the source rate differs (Whisper's native rate).
        import numpy as np
        audio = audio_float32
        if samplerate != 16000:
            try:
                from math import gcd
                from scipy.signal import resample_poly
                g = gcd(16000, samplerate)
                audio = resample_poly(audio, 16000 // g, samplerate // g).astype(np.float32)
            except Exception:
                import librosa
                audio = librosa.resample(audio, orig_sr=samplerate, target_sr=16000)

        segments, _info = self._model.transcribe(
            audio,
            language=self.language,
            beam_size=1,          # faster; quality tradeoff is minor for short segments
            vad_filter=False,     # Segmenter already did this
            condition_on_previous_text=False,
        )
        return " ".join(s.text for s in segments).strip()
