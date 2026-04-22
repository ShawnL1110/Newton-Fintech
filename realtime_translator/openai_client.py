import io
import wave

import numpy as np
from openai import OpenAI


class Translator:
    """Transcribes audio via Whisper and translates the result into Simplified Chinese."""

    def __init__(
        self,
        samplerate,
        transcribe_model="gpt-4o-mini-transcribe",
        translate_model="gpt-4o-mini",
        target_language="Simplified Chinese",
    ):
        self.client = OpenAI()
        self.samplerate = samplerate
        self.transcribe_model = transcribe_model
        self.translate_model = translate_model
        self.target_language = target_language

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
        resp = self.client.audio.transcriptions.create(
            model=self.transcribe_model,
            file=wav,
        )
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
        return (resp.choices[0].message.content or "").strip()

    @staticmethod
    def _already_chinese(text):
        if not text:
            return False
        # Japanese (hiragana/katakana) or Korean (hangul) → not Chinese, translate it.
        # Japanese kanji overlap with CJK ideographs, so presence of kana is the reliable signal.
        for c in text:
            if "぀" <= c <= "ヿ":
                return False
            if "가" <= c <= "힯":
                return False
        chinese = sum(1 for c in text if "一" <= c <= "鿿")
        return chinese / len(text) > 0.5
