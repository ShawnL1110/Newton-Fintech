"""Real-time macOS system-audio to Chinese subtitle tool.

Setup (macOS):
    1. brew install --cask blackhole-2ch
    2. «Audio MIDI Setup» → Multi-Output Device (speakers + BlackHole)
       set as system output.
    3. pip install -r requirements.txt
    4. export OPENAI_API_KEY=sk-...
    5. python -m realtime_translator.main  [--engine {batch,realtime,mixed}]

Engines:
    batch     — OpenAI transcribe + OpenAI translate (default, 稳健)
    realtime  — OpenAI Realtime API (streaming, 低延迟, 较贵)
    mixed     — 本地 faster-whisper 转写 + OpenAI 翻译 (几乎免费)
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import traceback

from .audio import AudioCapture, Segmenter, SpeakerClusterer
from .openai_client import CostTracker
from .pipeline import ERROR_MARKER, EnginePipeline
from .ui import SubtitleWindow


ENGINE_LABELS = {
    "batch": "OpenAI",
    "realtime": "Realtime",
    "mixed": "Mixed (本地+OpenAI)",
}


def parse_args():
    p = argparse.ArgumentParser(description="实时把电脑播放的音频翻译成中文")
    p.add_argument("--device", default="BlackHole", help="输入设备名称的子串 (默认 BlackHole)")
    p.add_argument("--list-devices", action="store_true", help="列出可用的输入设备并退出")
    p.add_argument("--engine", choices=["batch", "realtime", "mixed"], default="batch",
                   help="batch=OpenAI; realtime=Realtime API; mixed=本地转写+OpenAI翻译")
    p.add_argument("--transcribe-model", default="gpt-4o-mini-transcribe")
    p.add_argument("--translate-model", default="gpt-4o-mini")
    p.add_argument("--realtime-model", default="gpt-4o-mini-realtime-preview")
    p.add_argument("--whisper-model", default="small",
                   help="本地 Whisper 模型大小: tiny|base|small|medium|large-v3 (默认 small)")
    p.add_argument("--no-diarization", action="store_true", help="关闭说话人区分")
    return p.parse_args()


def main():
    args = parse_args()

    if args.list_devices:
        for idx, name, ch in AudioCapture.list_input_devices():
            print(f"[{idx}] {name}  (in={ch})")
        return

    if not os.environ.get("OPENAI_API_KEY"):
        print("错误: 请先设置环境变量 OPENAI_API_KEY", file=sys.stderr)
        sys.exit(1)

    try:
        capture = AudioCapture(device_name=args.device)
    except RuntimeError as e:
        print(f"错误: {e}", file=sys.stderr)
        print("可用输入设备:", file=sys.stderr)
        for idx, name, ch in AudioCapture.list_input_devices():
            print(f"  [{idx}] {name}  (in={ch})", file=sys.stderr)
        sys.exit(1)

    cost = CostTracker()
    segment_queue: queue.Queue = queue.Queue()
    segmenter = Segmenter(capture.queue, segment_queue, samplerate=capture.samplerate)

    clusterer = None
    if not args.no_diarization:
        try:
            clusterer = SpeakerClusterer(samplerate=capture.samplerate)
        except Exception:
            traceback.print_exc()
            print("说话人识别初始化失败，回退到单一说话人模式", file=sys.stderr)
            clusterer = None

    window = SubtitleWindow()
    window.set_level_provider(lambda: capture.current_level)

    # Mutable holder so poll_results + the engine-change callback both see
    # the current pipeline across hot-swaps.
    state = {"pipeline": None, "engine": args.engine}

    def set_engine_status():
        label = ENGINE_LABELS.get(state["engine"], state["engine"])
        window.set_status(
            f"● 监听中 · {label} · {capture.device_info['name']} @ {capture.samplerate}Hz"
        )

    def start_pipeline(engine):
        pipeline = EnginePipeline(
            engine=engine,
            capture=capture,
            segment_queue=segment_queue,
            clusterer=clusterer,
            cost=cost,
            args=args,
        )
        pipeline.start()
        return pipeline

    state["pipeline"] = start_pipeline(args.engine)
    set_engine_status()
    window.set_cost("$0.0000")

    # ---- poll loops ----

    def poll_results():
        drained = False
        try:
            while True:
                speaker_id, original, translation = state["pipeline"].result_queue.get_nowait()
                if original == ERROR_MARKER:
                    window.set_status(f"● 错误: {translation[:80]}")
                    drained = False
                    continue
                window.append_line(speaker_id or 0, original, translation)
                drained = True
        except queue.Empty:
            pass
        if drained:
            set_engine_status()
        window.after(120, poll_results)

    def poll_cost():
        total = cost.total_usd
        fmt = f"${total:.4f}" if total < 1 else f"${total:.2f}"
        window.set_cost(fmt)
        window.after(1000, poll_cost)

    def shutdown():
        if state["pipeline"] is not None:
            state["pipeline"].stop()
        segmenter.stop()
        segment_queue.put(None)
        try:
            capture.stop()
        except Exception:
            pass
        window.destroy()

    window.on_close(shutdown)

    threading.Thread(target=segmenter.run, daemon=True).start()
    capture.start()

    window.after(120, poll_results)
    window.after(1000, poll_cost)
    try:
        window.run()
    finally:
        shutdown()


if __name__ == "__main__":
    main()
