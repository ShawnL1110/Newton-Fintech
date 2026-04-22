import queue
import threading

import numpy as np
import sounddevice as sd


class AudioCapture:
    """Captures system audio from a loopback device (e.g. BlackHole on macOS).

    Supports multiple consumers: every captured chunk is fanned out to
    ``self.queue`` plus any extra queues registered via ``add_listener``
    / ``remove_listener``. Mutation is lock-guarded so the audio callback
    and the main thread can co-exist safely.

    Also exposes ``current_level`` — an EMA-smoothed RMS of the latest
    chunks (0..~0.7 for most speech) that UIs can poll at display rate
    without having to drain the raw stream.
    """

    def __init__(self, device_name="BlackHole", chunk_duration=0.1, out_queue=None):
        self.device_index, self.device_info = self._find_device(device_name)
        self.samplerate = int(self.device_info["default_samplerate"])
        self.channels = min(int(self.device_info["max_input_channels"]), 2) or 1
        self.chunk_samples = int(self.samplerate * chunk_duration)
        self.queue = out_queue if out_queue is not None else queue.Queue()
        self._listeners = [self.queue]
        self._listeners_lock = threading.Lock()
        self.current_level = 0.0
        self.stream = None

    def add_listener(self, q):
        """Register an additional queue to receive every captured chunk."""
        with self._listeners_lock:
            self._listeners.append(q)

    def remove_listener(self, q):
        """Unregister a previously-added listener queue (no-op if missing)."""
        with self._listeners_lock:
            try:
                self._listeners.remove(q)
            except ValueError:
                pass

    @staticmethod
    def list_input_devices():
        return [
            (i, d["name"], int(d["max_input_channels"]))
            for i, d in enumerate(sd.query_devices())
            if d["max_input_channels"] > 0
        ]

    def _find_device(self, name):
        needle = name.lower()
        for i, dev in enumerate(sd.query_devices()):
            if needle in dev["name"].lower() and dev["max_input_channels"] > 0:
                return i, dev
        raise RuntimeError(
            f"找不到名为 '{name}' 的输入设备。请先安装 BlackHole，"
            "并在「音频 MIDI 设置」中创建 Multi-Output Device。"
        )

    def _callback(self, indata, frames, time_info, status):
        if indata.ndim > 1:
            mono = indata.mean(axis=1)
        else:
            mono = indata[:, 0] if indata.ndim == 2 else indata
        chunk = mono.astype(np.float32).copy()

        # EMA-smoothed RMS for UI polling.
        rms = float(np.sqrt(np.mean(chunk * chunk))) if len(chunk) else 0.0
        self.current_level = self.current_level * 0.6 + rms * 0.4

        with self._listeners_lock:
            listeners = list(self._listeners)
        for q in listeners:
            q.put(chunk)

    def start(self):
        self.stream = sd.InputStream(
            device=self.device_index,
            channels=self.channels,
            samplerate=self.samplerate,
            blocksize=self.chunk_samples,
            dtype="float32",
            callback=self._callback,
        )
        self.stream.start()

    def stop(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None


class Segmenter:
    """Groups small audio chunks into speech segments bounded by silence."""

    def __init__(
        self,
        input_queue,
        output_queue,
        samplerate,
        silence_threshold=0.008,
        silence_duration=0.7,
        min_segment_duration=0.8,
        max_segment_duration=15.0,
    ):
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.samplerate = samplerate
        self.silence_threshold = silence_threshold
        self.silence_samples = int(silence_duration * samplerate)
        self.min_samples = int(min_segment_duration * samplerate)
        self.max_samples = int(max_segment_duration * samplerate)
        self._stop = threading.Event()

    def run(self):
        buffer = []
        buffered = 0
        silence_run = 0
        has_speech = False

        while not self._stop.is_set():
            try:
                chunk = self.input_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            buffer.append(chunk)
            buffered += len(chunk)

            rms = float(np.sqrt(np.mean(chunk * chunk))) if len(chunk) else 0.0
            if rms < self.silence_threshold:
                silence_run += len(chunk)
            else:
                silence_run = 0
                has_speech = True

            emit = False
            if has_speech and silence_run >= self.silence_samples and buffered >= self.min_samples:
                emit = True
            elif buffered >= self.max_samples and has_speech:
                emit = True
            elif buffered >= self.max_samples:
                buffer.clear()
                buffered = 0
                silence_run = 0
                has_speech = False

            if emit:
                segment = np.concatenate(buffer)
                self.output_queue.put(segment)
                buffer.clear()
                buffered = 0
                silence_run = 0
                has_speech = False

    def stop(self):
        self._stop.set()


class SpeakerClusterer:
    """Online speaker clustering using Resemblyzer voice embeddings.

    For each audio segment, extract a 256-dim embedding and match it against
    known speaker centroids via cosine similarity. If the best match is above
    ``similarity_threshold`` it's the same speaker (centroid updated by running
    average); otherwise a new speaker slot is created, up to ``max_speakers``.

    Segments shorter than ~1s cannot produce a reliable embedding; they are
    attributed to the most recently active speaker (or speaker 0 if none yet).
    """

    def __init__(self, samplerate, similarity_threshold=0.75, max_speakers=8):
        from resemblyzer import VoiceEncoder, preprocess_wav  # heavy imports

        self._preprocess_wav = preprocess_wav
        self._encoder = VoiceEncoder(verbose=False)
        self.samplerate = samplerate
        self.threshold = similarity_threshold
        self.max_speakers = max_speakers

        self._centroids = []
        self._counts = []
        self._last_speaker = 0

    @property
    def last_speaker(self):
        return self._last_speaker

    def _fallback(self):
        return self._last_speaker if self._centroids else 0

    def assign(self, audio_float32):
        if len(audio_float32) < int(self.samplerate * 1.0):
            return self._fallback()

        try:
            wav = self._preprocess_wav(audio_float32, source_sr=self.samplerate)
        except Exception:
            return self._fallback()

        if wav is None or len(wav) < 16000:
            return self._fallback()

        try:
            embed = self._encoder.embed_utterance(wav)
        except Exception:
            return self._fallback()

        if not self._centroids:
            self._centroids.append(embed)
            self._counts.append(1)
            self._last_speaker = 0
            return 0

        def cos(a, b):
            return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))

        sims = [cos(c, embed) for c in self._centroids]
        best_idx = int(np.argmax(sims))

        if sims[best_idx] >= self.threshold:
            n = self._counts[best_idx]
            self._centroids[best_idx] = (self._centroids[best_idx] * n + embed) / (n + 1)
            self._counts[best_idx] = n + 1
            self._last_speaker = best_idx
            return best_idx

        if len(self._centroids) < self.max_speakers:
            self._centroids.append(embed)
            self._counts.append(1)
            new_idx = len(self._centroids) - 1
            self._last_speaker = new_idx
            return new_idx

        self._last_speaker = best_idx
        return best_idx
