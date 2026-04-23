"""OpenAI Realtime API streaming client.

Connects to gpt-4o-*-realtime-preview via WebSocket (wrapped by the OpenAI
SDK's async client), streams 24kHz PCM16 audio, and emits 3-tuples as
translations come in:

    ("__partial__", original, translation)   — streaming delta; consumer
        should keep replacing the tail line in place while it grows
    (original, "", translation)              — final result for a turn
    ("__error__", message, "")               — error surfaced to UI

Runs an asyncio event loop in its own daemon thread; audio chunks are
accepted from any thread via push_audio() and bridged into the loop
through a thread-safe queue.
"""

from __future__ import annotations

import asyncio
import base64
import queue
import threading
import traceback

import numpy as np


TARGET_SR = 24000  # Realtime API input rate


def _resample_to_24k(audio_f32, src_sr):
    """Resample mono float32 to 24kHz. Prefer zero-dep paths where possible."""
    if src_sr == TARGET_SR:
        return audio_f32
    if src_sr == 48000:
        # Integer 2:1 decimation with simple averaging as a cheap anti-alias.
        n = len(audio_f32) - (len(audio_f32) % 2)
        return (audio_f32[:n:2] + audio_f32[1:n:2]) * 0.5
    try:
        from math import gcd
        from scipy.signal import resample_poly
        g = gcd(TARGET_SR, src_sr)
        return resample_poly(audio_f32, TARGET_SR // g, src_sr // g).astype(np.float32)
    except Exception:
        import librosa
        return librosa.resample(audio_f32, orig_sr=src_sr, target_sr=TARGET_SR)


def _to_pcm16_bytes(audio_f32):
    pcm = np.clip(audio_f32, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16)
    return pcm.tobytes()


class RealtimeClient:
    """Streams audio to OpenAI Realtime API and emits translation events."""

    def __init__(
        self,
        samplerate,
        cost_tracker,
        model="gpt-4o-mini-realtime-preview",
        transcribe_model="gpt-4o-mini-transcribe",
        target_language="Simplified Chinese",
        live_mode=False,
        commit_interval=1.5,
    ):
        self.samplerate = samplerate
        self.cost = cost_tracker
        self.model = model
        self.transcribe_model = transcribe_model
        self.target_language = target_language
        self.live_mode = live_mode
        self.commit_interval = commit_interval

        # Thread-safe channels used across the UI / audio / asyncio threads.
        self.result_queue: queue.Queue = queue.Queue()
        self._audio_in: queue.Queue = queue.Queue()

        # Track peak RMS since the last commit so live mode can skip
        # commits over silent intervals (which otherwise produce
        # hallucinated refusals like "对不起，我无法处理这个请求"). Plain
        # float read/write is atomic under the GIL, no lock needed.
        self._peak_rms = 0.0
        self._silence_threshold = 0.012

        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread = None

    # ---- public API (any thread) ----

    def start(self, wait_for_ready=True, ready_timeout=15.0):
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()
        if wait_for_ready:
            self._ready.wait(timeout=ready_timeout)

    def stop(self):
        self._stop.set()
        self._audio_in.put(None)

    def push_audio(self, audio_f32):
        if self._stop.is_set():
            return
        if len(audio_f32):
            rms = float(np.sqrt(np.mean(audio_f32 * audio_f32)))
            if rms > self._peak_rms:
                self._peak_rms = rms
        self._audio_in.put(audio_f32)

    # ---- asyncio machinery ----

    def _thread_main(self):
        try:
            asyncio.run(self._async_main())
        except Exception as e:
            traceback.print_exc()
            self.result_queue.put(("__error__", f"Realtime: {e}", ""))

    async def _async_main(self):
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            self.result_queue.put(("__error__", f"openai SDK missing: {e}", ""))
            return

        client = AsyncOpenAI()
        audio_q: asyncio.Queue = asyncio.Queue(maxsize=200)

        async def bridge_audio():
            loop = asyncio.get_event_loop()
            while not self._stop.is_set():
                chunk = await loop.run_in_executor(None, self._audio_in.get)
                if chunk is None:
                    await audio_q.put(None)
                    return
                try:
                    audio_q.put_nowait(chunk)
                except asyncio.QueueFull:
                    # Drop oldest if producer outruns API (shouldn't happen).
                    try:
                        audio_q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    await audio_q.put(chunk)

        try:
            async with client.beta.realtime.connect(model=self.model) as conn:
                if self.live_mode:
                    # Live (同传) mode: disable server VAD, drive turns
                    # ourselves via _commit_loop every commit_interval seconds.
                    turn_detection = None
                    instructions = (
                        f"You are a live simultaneous interpreter. Translate the audio "
                        f"fragments into natural, fluent {self.target_language} as they "
                        "arrive. Each fragment may end mid-sentence — translate exactly "
                        "what you've heard, even if incomplete; do NOT invent or guess "
                        "the rest. Skip filler if there's no real content. Output ONLY "
                        "the translation, no quotes, no pinyin, no explanations."
                    )
                else:
                    turn_detection = {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 500,
                        "create_response": True,
                    }
                    instructions = (
                        f"You are a simultaneous interpreter. Translate the user's "
                        f"speech into natural, fluent {self.target_language}. "
                        "The input may be a fragment of ongoing speech — translate "
                        "it as-is without adding context. Output ONLY the "
                        "translation, no quotes, no pinyin, no explanations."
                    )

                await conn.session.update(session={
                    "modalities": ["text"],
                    "input_audio_format": "pcm16",
                    "input_audio_transcription": {"model": self.transcribe_model},
                    "turn_detection": turn_detection,
                    "instructions": instructions,
                })
                self._ready.set()

                tasks = [
                    bridge_audio(),
                    self._pump_audio(conn, audio_q),
                    self._read_events(conn),
                ]
                if self.live_mode:
                    tasks.append(self._commit_loop(conn))
                await asyncio.gather(*tasks)
        except Exception as e:
            traceback.print_exc()
            self.result_queue.put(("__error__", f"Realtime: {e}", ""))

    async def _pump_audio(self, conn, audio_q):
        while True:
            chunk = await audio_q.get()
            if chunk is None:
                return
            resampled = _resample_to_24k(chunk, self.samplerate)
            pcm = _to_pcm16_bytes(resampled)
            b64 = base64.b64encode(pcm).decode("ascii")
            try:
                await conn.input_audio_buffer.append(audio=b64)
            except Exception as e:
                self.result_queue.put(("__error__", f"audio append: {e}", ""))
                return

    async def _read_events(self, conn):
        current_orig = ""
        current_trans = ""
        async for event in conn:
            et = getattr(event, "type", "")
            if et == "conversation.item.input_audio_transcription.completed":
                current_orig = getattr(event, "transcript", "") or ""
                # Transcription arrived; push a partial so the UI shows the
                # original line even before translation starts streaming.
                if current_orig:
                    self.result_queue.put(("__partial__", current_orig, current_trans))
            elif et == "response.text.delta":
                current_trans += getattr(event, "delta", "") or ""
                # Stream every accumulated delta — the UI replaces the tail
                # in place, so spam here is fine and gives the lyrics feel.
                self.result_queue.put(("__partial__", current_orig, current_trans))
            elif et == "response.text.done":
                current_trans = getattr(event, "text", None) or current_trans
                self.result_queue.put(("__partial__", current_orig, current_trans))
            elif et == "response.done":
                if current_orig or current_trans:
                    # Final form: first element is the original text so the
                    # bridge distinguishes it from __partial__ / __error__.
                    self.result_queue.put((current_orig, "", current_trans))
                self._record_usage(event)
                current_orig = ""
                current_trans = ""
            elif et == "error":
                err = getattr(event, "error", None)
                msg = getattr(err, "message", None) if err else None
                self.result_queue.put(("__error__", msg or "unknown error", ""))

    async def _commit_loop(self, conn):
        """Live mode: every commit_interval seconds, force-commit the audio
        buffer and request a response. Gives true simultaneous-interpretation
        feel — translations stream out mid-sentence without waiting for the
        speaker to pause.

        Skips commits when the past interval was silent so the model doesn't
        hallucinate refusals on empty audio. Clears the buffer in that case
        so silent samples don't accumulate forever.
        """
        while not self._stop.is_set():
            await asyncio.sleep(self.commit_interval)
            peak = self._peak_rms
            self._peak_rms = 0.0  # reset window for next interval

            if peak < self._silence_threshold:
                # Silent interval — drop the buffered audio; don't commit.
                try:
                    await conn.input_audio_buffer.clear()
                except Exception:
                    pass
                continue

            try:
                await conn.input_audio_buffer.commit()
                await conn.response.create()
            except Exception as e:
                # Empty buffer or in-flight response: harmless, skip this tick.
                msg = str(e).lower()
                if "buffer" in msg or "active response" in msg or "no audio" in msg:
                    continue
                self.result_queue.put(("__error__", f"commit: {e}", ""))
                return

    def _record_usage(self, event):
        """Tag this turn's audio/text usage in the CostTracker."""
        response = getattr(event, "response", None)
        usage = getattr(response, "usage", None) if response else None
        if not usage:
            return
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        details = getattr(usage, "input_token_details", None)
        audio_in = 0
        text_in = input_tokens
        if details is not None:
            audio_in = getattr(details, "audio_tokens", 0) or 0
            text_attr = getattr(details, "text_tokens", None)
            text_in = text_attr if text_attr is not None else max(0, input_tokens - audio_in)
        self.cost.add_audio_tokens(audio_in, self.model)
        self.cost.add_text_tokens(text_in, output_tokens, self.model)
