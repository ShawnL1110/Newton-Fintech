import io
import wave

import numpy as np
from openai import OpenAI


# OpenAI pricing (USD). Keys follow uniform per-unit naming so the tracker
# can multiply amount * rate without per-model branching.
#   audio_minute  = $ per minute of audio (transcribe endpoints)
#   audio_1k_in   = $ per 1k audio tokens (realtime input)
#   text_1k_in    = $ per 1k text input tokens
#   text_1k_out   = $ per 1k text output tokens
MODEL_PRICING = {
    "gpt-4o-mini-transcribe":       {"audio_minute": 0.003},
    "gpt-4o-transcribe":            {"audio_minute": 0.006},
    "whisper-1":                    {"audio_minute": 0.006},
    "gpt-4o-mini":                  {"text_1k_in": 0.00015, "text_1k_out": 0.0006},
    "gpt-4o":                       {"text_1k_in": 0.0025,  "text_1k_out": 0.01},
    "gpt-4o-realtime-preview":      {"audio_1k_in": 0.040,  "text_1k_in": 0.005,    "text_1k_out": 0.020},
    "gpt-4o-mini-realtime-preview": {"audio_1k_in": 0.010,  "text_1k_in": 0.00060,  "text_1k_out": 0.00240},
}


class CostTracker:
    """Accumulates OpenAI API usage across a session and estimates spend.

    Each recorded datum is tagged with its model so a single session can
    mix batch transcribe + chat translate and realtime streaming.
    """

    def __init__(self):
        self._entries = []  # list of (model, kind, amount)

    def _add(self, model, kind, amount):
        if amount:
            self._entries.append((model, kind, amount))

    def add_audio_seconds(self, seconds, model):
        """Transcribe endpoints bill per minute of audio."""
        self._add(model, "audio_minute", seconds / 60.0)

    def add_audio_tokens(self, tokens, model):
        """Realtime API bills audio input per 1k tokens."""
        self._add(model, "audio_1k_in", tokens / 1000.0)

    def add_text_tokens(self, input_tokens, output_tokens, model):
        self._add(model, "text_1k_in", input_tokens / 1000.0)
        self._add(model, "text_1k_out", output_tokens / 1000.0)

    @property
    def total_usd(self):
        total = 0.0
        for model, kind, amount in self._entries:
            rate = MODEL_PRICING.get(model, {}).get(kind, 0.0)
            total += amount * rate
        return total


class Translator:
    """Transcribes audio via Whisper and translates the result into Simplified Chinese."""

    def __init__(
        self,
        samplerate,
        transcribe_model="gpt-4o-mini-transcribe",
        translate_model="gpt-4o-mini",
        target_language="Simplified Chinese",
        cost_tracker=None,
    ):
        self.client = OpenAI()
        self.samplerate = samplerate
        self.transcribe_model = transcribe_model
        self.translate_model = translate_model
        self.target_language = target_language
        self.cost = cost_tracker if cost_tracker is not None else CostTracker()

    def _audio_to_wav(self, audio_float32):
        pcm16 = np.clip(audio_float32, -1.0, 1.0)
        pcm16 = (pcm16 * 32767.0).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.samplerate)
            wf.writeframes(pcm16.tobytes())
        buf.seek(0)
        buf.name = "audio.wav"
        return buf

    def transcribe(self, audio):
        wav = self._audio_to_wav(audio)
        duration_sec = len(audio) / float(self.samplerate)
        resp = self.client.audio.transcriptions.create(
            model=self.transcribe_model,
            file=wav,
        )
        self.cost.add_audio_seconds(duration_sec, self.transcribe_model)
        return (resp.text or "").strip()

    def translate(self, text):
        if not text:
            return ""
        if self._already_chinese(text):
            return text
        resp = self.client.chat.completions.create(
            model=self.translate_model,
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You translate text into natural, fluent {self.target_language}. "
                        "The text may be a short fragment from ongoing speech — translate it "
                        "as-is without adding context. Output ONLY the translation, no quotes, "
                        "no pinyin, no explanations."
                    ),
                },
                {"role": "user", "content": text},
            ],
        )
        if getattr(resp, "usage", None):
            self.cost.add_text_tokens(
                getattr(resp.usage, "prompt_tokens", 0) or 0,
                getattr(resp.usage, "completion_tokens", 0) or 0,
                self.translate_model,
            )
        return (resp.choices[0].message.content or "").strip()

    @staticmethod
    def _already_chinese(text):
        if not text:
            return False
        for c in text:
            if "぀" <= c <= "ヿ":
                return False
            if "가" <= c <= "힯":
                return False
        chinese = sum(1 for c in text if "一" <= c <= "鿿")
        return chinese / len(text) > 0.5
