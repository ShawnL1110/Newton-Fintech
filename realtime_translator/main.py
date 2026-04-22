"""Real-time macOS system-audio to Chinese subtitle tool.

Setup (macOS):
    1. Install BlackHole 2ch:
           brew install --cask blackhole-2ch
    2. Open «Audio MIDI Setup» → create a Multi-Output Device containing both
       your speakers/headphones AND BlackHole 2ch. Set it as system output so
       you still hear the audio while it's captured.
    3. pip install -r requirements.txt
    4. export OPENAI_API_KEY=sk-...
    5. python -m realtime_translator.main

Options:
    --device NAME       substring of input device name (default: BlackHole)
    --list-devices      print available input devices and exit
    --no-diarization    disable speaker identification
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import traceback

from .audio import AudioCapture, Segmenter, SpeakerClusterer
from .openai_client import CostTracker, Translator
from .ui import SubtitleWindow


def parse_args():
    p = argparse.ArgumentParser(description="实时把电脑播放的音频翻译成中文")
    p.add_argument("--device", default="BlackHole", help="输入设备名称的子串 (默认 BlackHole)")
    p.add_argument("--list-devices", action="store_true", help="列出可用的输入设备并退出")
    p.add_argument("--transcribe-model", default="gpt-4o-mini-transcribe")
    p.add_argument("--translate-model", default="gpt-4o-mini")
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

    segment_queue: queue.Queue = queue.Queue()
    result_queue: queue.Queue = queue.Queue()

    cost = CostTracker()
    segmenter = Segmenter(capture.queue, segment_queue, samplerate=capture.samplerate)
    translator = Translator(
        samplerate=capture.samplerate,
        transcribe_model=args.transcribe_model,
        translate_model=args.translate_model,
        cost_tracker=cost,
    )

    clusterer = None
    if not args.no_diarization:
        try:
            clusterer = SpeakerClusterer(samplerate=capture.samplerate)
        except Exception:
            traceback.print_exc()
            print("说话人识别初始化失败，回退到单一说话人模式", file=sys.stderr)
            clusterer = None

    window = SubtitleWindow()
    window.set_status(f"● 监听中 · {capture.device_info['name']} @ {capture.samplerate}Hz")
    window.set_cost("$0.0000")

    stop_event = threading.Event()

    def processing_worker():
        while not stop_event.is_set():
            try:
                segment = segment_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if segment is None:
                break
            try:
                speaker_id = clusterer.assign(segment) if clusterer else 0
                text = translator.transcribe(segment)
                if not text:
                    continue
                zh = translator.translate(text)
                result_queue.put((speaker_id, text, zh or ""))
            except Exception:
                traceback.print_exc()

    def poll_results():
        drained = False
        try:
            while True:
                speaker_id, original, translation = result_queue.get_nowait()
                window.append_line(speaker_id, original, translation)
                drained = True
        except queue.Empty:
            pass
        if drained:
            window.set_status("● 监听中")
        window.after(120, poll_results)

    def poll_cost():
        total = cost.total_usd
        # Show 4 decimals under $1, 2 decimals above (keeps tiny costs visible).
        fmt = f"${total:.4f}" if total < 1 else f"${total:.2f}"
        window.set_cost(fmt)
        window.after(1000, poll_cost)

    def shutdown():
        stop_event.set()
        segmenter.stop()
        segment_queue.put(None)
        try:
            capture.stop()
        except Exception:
            pass
        window.destroy()

    window.on_close(shutdown)

    seg_thread = threading.Thread(target=segmenter.run, daemon=True)
    proc_thread = threading.Thread(target=processing_worker, daemon=True)
    seg_thread.start()
    proc_thread.start()
    capture.start()

    window.after(120, poll_results)
    window.after(1000, poll_cost)
    try:
        window.run()
    finally:
        shutdown()


if __name__ == "__main__":
    main()
