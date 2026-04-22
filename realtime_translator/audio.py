import queue
import threading

import numpy as np
import sounddevice as sd


class AudioCapture:
    """Captures system audio from a loopback device (e.g. BlackHole on macOS)."""

    def __init__(self, device_name="BlackHole", chunk_duration=0.1, out_queue=None):
        self.device_index, self.device_info = self._find_device(device_name)
        self.samplerate = int(self.device_info["default_samplerate"])
        self.channels = min(int(self.device_info["max_input_channels"]), 2) or 1
        self.chunk_samples = int(self.samplerate * chunk_duration)
        self.queue = out_queue if out_queue is not None else queue.Queue()
        self.stream = None

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
            f"找不到名为 '{name}' 的输入设备。请先安装 BlackHole,"
            "并在「音频 MIDI 设置」中创建 Multi-Output Device。"
        )

    def _callback(self, indata, frames, time_info, status):
        if indata.ndim > 1:
            mono = indata.mean(axis=1)
        else:
            mono = indata[:, 0] if indata.ndim == 2 else indata
        self.queue.put(mono.astype(np.float32).copy())

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
                # drop long silence, avoid unbounded buffer
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
