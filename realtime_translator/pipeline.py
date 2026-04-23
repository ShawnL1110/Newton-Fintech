"""Swappable engine pipeline.

An ``EnginePipeline`` owns all the per-engine state (API clients, model
handles, worker threads) and exposes a unified ``result_queue`` of
``(speaker_id, original, translation, is_partial)`` tuples regardless of
engine. ``is_partial=True`` means the tail is still streaming and the UI
should replace the last line in place instead of appending.

The capture / segmenter / clusterer / cost-tracker are *shared* across
pipeline swaps and managed by the caller. Pipelines must never stop
those shared components.

Errors from an engine surface as
``(None, "__error__", message, False)`` on the result queue so the UI
layer can display them in the status bar without crashing.
"""

from __future__ import annotations

import queue
import threading
import traceback


ERROR_MARKER = "__error__"
PARTIAL_MARKER = "__partial__"
VALID_ENGINES = ("batch", "realtime", "mixed")


class EnginePipeline:
    """Runs one engine's transcription + translation workers."""

    def __init__(self, engine, capture, segment_queue, clusterer, cost, args):
        if engine not in VALID_ENGINES:
            raise ValueError(f"unknown engine: {engine!r}")
        self.engine = engine
        self.capture = capture
        self.segment_queue = segment_queue
        self.clusterer = clusterer
        self.cost = cost
        self.args = args

        self.result_queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._threads = []

        # engine-specific state (populated during start)
        self._translator = None
        self._rt_client = None
        self._rt_audio_q = None
        self._local_whisper = None

    # ---- lifecycle ----

    def start(self):
        """Spin up engine-specific resources and workers."""
        try:
            if self.engine == "batch":
                self._start_batch()
            elif self.engine == "realtime":
                self._start_realtime()
            elif self.engine == "mixed":
                self._start_mixed()
        except Exception as e:
            traceback.print_exc()
            self.result_queue.put((None, ERROR_MARKER, f"启动失败: {e}", False))

    def stop(self, join_timeout=3.0):
        """Tell all workers to exit and clean up engine-specific resources."""
        self._stop.set()

        if self._rt_audio_q is not None:
            self.capture.remove_listener(self._rt_audio_q)
            self._rt_audio_q.put(None)  # unblock bridge worker

        if self._rt_client is not None:
            try:
                self._rt_client.stop()
            except Exception:
                pass

        for t in self._threads:
            t.join(timeout=join_timeout)

        self._translator = None
        self._rt_client = None
        self._rt_audio_q = None
        self._local_whisper = None
        self._threads = []

    # ---- engine setup ----

    def _start_batch(self):
        from .openai_client import Translator
        self._translator = Translator(
            samplerate=self.capture.samplerate,
            transcribe_model=self.args.transcribe_model,
            translate_model=self.args.translate_model,
            cost_tracker=self.cost,
        )
        self._spawn(self._batch_worker)

    def _start_realtime(self):
        from .realtime_client import RealtimeClient
        self._rt_client = RealtimeClient(
            samplerate=self.capture.samplerate,
            cost_tracker=self.cost,
            model=self.args.realtime_model,
            transcribe_model=self.args.transcribe_model,
        )
        self._rt_audio_q = queue.Queue()
        self.capture.add_listener(self._rt_audio_q)

        self._spawn(self._diarization_worker)
        self._spawn(self._rt_audio_bridge)
        self._spawn(self._rt_result_bridge)
        self._rt_client.start(wait_for_ready=False)

    def _start_mixed(self):
        from .local_whisper import LocalWhisperTranscriber
        from .openai_client import Translator

        self._local_whisper = LocalWhisperTranscriber(
            model_size=getattr(self.args, "whisper_model", "small"),
        )
        self._translator = Translator(
            samplerate=self.capture.samplerate,
            transcribe_model=self.args.transcribe_model,
            translate_model=self.args.translate_model,
            cost_tracker=self.cost,
        )
        self._spawn(self._mixed_worker)

    def _spawn(self, target):
        t = threading.Thread(target=target, daemon=True)
        t.start()
        self._threads.append(t)

    # ---- workers ----

    def _batch_worker(self):
        while not self._stop.is_set():
            try:
                segment = self.segment_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if segment is None:
                # Sentinel used by external shutdown; put it back so other
                # consumers (if any) also see it, then exit.
                self.segment_queue.put(None)
                return
            try:
                speaker_id = self.clusterer.assign(segment) if self.clusterer else 0
                text = self._translator.transcribe(segment)
                if not text:
                    continue
                zh = self._translator.translate(text)
                self.result_queue.put((speaker_id, text, zh or "", False))
            except Exception:
                traceback.print_exc()

    def _mixed_worker(self):
        while not self._stop.is_set():
            try:
                segment = self.segment_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if segment is None:
                self.segment_queue.put(None)
                return
            try:
                speaker_id = self.clusterer.assign(segment) if self.clusterer else 0
                text = self._local_whisper.transcribe(segment, self.capture.samplerate)
                if not text:
                    continue
                zh = self._translator.translate(text)
                self.result_queue.put((speaker_id, text, zh or "", False))
            except Exception:
                traceback.print_exc()

    def _diarization_worker(self):
        """Realtime mode: segments only feed the speaker clusterer."""
        while not self._stop.is_set():
            try:
                segment = self.segment_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if segment is None:
                self.segment_queue.put(None)
                return
            if self.clusterer:
                try:
                    self.clusterer.assign(segment)
                except Exception:
                    traceback.print_exc()

    def _rt_audio_bridge(self):
        while not self._stop.is_set():
            try:
                chunk = self._rt_audio_q.get(timeout=0.2)
            except queue.Empty:
                continue
            if chunk is None:
                return
            if self._rt_client is not None:
                self._rt_client.push_audio(chunk)

    def _rt_result_bridge(self):
        """Forward RealtimeClient events into the pipeline's unified queue.

        The client emits 3-tuples where the first element is either the
        PARTIAL_MARKER (streaming delta; keep updating the tail), the
        ERROR_MARKER, or the original-transcription text (final result).
        """
        while not self._stop.is_set():
            if self._rt_client is None:
                return
            try:
                first, original, translation = self._rt_client.result_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            except ValueError:
                continue  # unexpected payload shape
            if first == ERROR_MARKER:
                self.result_queue.put((None, ERROR_MARKER, original, False))
                continue
            speaker_id = self.clusterer.last_speaker if self.clusterer else 0
            if first == PARTIAL_MARKER:
                self.result_queue.put((speaker_id, original, translation, True))
            else:
                # Final turn: first is the original transcription text.
                self.result_queue.put((speaker_id, first, translation, False))
