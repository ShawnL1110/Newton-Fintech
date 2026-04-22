import io
import wave

import numpy as np
from openai import OpenAI


# Approximate OpenAI pricing (USD). Update as pricing changes.
# Transcribe models are billed per minute of audio; chat models per 1k tokens.
MODEL_PRICING = {
    "gpt-4o-mini-transcribe": {"audio_per_minute": 0.003},
    "gpt-4o-transcribe":      {"audio_per_minute": 0.006},
    "whisper-1":              {"audio_per_minute": 0.006},
    "gpt-4o-mini":            {"input_per_1k": 0.00015, "output_per_1k": 0.0006},
    "gpt-4o":                 {"input_per_1k": 0.0025,  "output_per_1k": 0.01},
}


class CostTracker:
    """Accumulates OpenAI API usage across a session and estimates spend."""

    def __init__(self):
        self.audio_seconds = 0.0
        self.input_tokens = 0
        self.output_tokens = 0
        self._transcribe_model = None
        self._chat_model = None

    def add_audio(self, seconds, model):
        self.audio_seconds += seconds
        self._transcribe_model = model

    def add_chat(self, input_tokens, output_tokens, model):
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self._chat_model = model

    @property
    def total_usd(self):
        total = 0.0
        if self._transcribe_model:
            p = MODEL_PRICING.get(self._transcribe_model, {})
            total += (self.audio_seconds / 60.0) * p.get("audio_per_minute", 0.0)
        if self._chat_model:
            p = MODEL_PRICING.get(self._chat_model, {})
            total += (self.input_tokens / 1000.0) * p.get("input_per_1k", 0.0)
            total += (self.output_tokens / 1000.0) * p.get("output_per_1k", 0.0)
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
        self.cost.add_audio(duration_sec, self.transcribe_model)
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
            self.cost.add_chat(
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
