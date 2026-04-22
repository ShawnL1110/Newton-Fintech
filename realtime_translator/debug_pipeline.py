"""Debug harness: prints each stage of the pipeline for 20 seconds."""

import queue
import threading
import time
import traceback

from realtime_translator.audio import AudioCapture, Segmenter
from realtime_translator.openai_client import Translator


def main():
    cap = AudioCapture(device_name="BlackHole")
    name = cap.device_info["name"]
    print(f"[device] {name} @ {cap.samplerate}Hz ch={cap.channels}")

    seg_q: queue.Queue = queue.Queue()
    seg = Segmenter(cap.queue, seg_q, samplerate=cap.samplerate)
    tr = Translator(samplerate=cap.samplerate)

    threading.Thread(target=seg.run, daemon=True).start()
    cap.start()
    print("[listening] 播放一段英文音频,20 秒内应该能看到输出...")

    end = time.time() + 20
    while time.time() < end:
        try:
            segment = seg_q.get(timeout=0.5)
        except queue.Empty:
            continue
        dur = len(segment) / cap.samplerate
        print(f"[segment] {len(segment)} samples ({dur:.1f}s)")
        try:
            text = tr.transcribe(segment)
            print(f"[transcribe] {text!r}")
            if text:
                zh = tr.translate(text)
                print(f"[translate]  {zh!r}")
        except Exception:
            traceback.print_exc()

    cap.stop()
    print("[done]")


if __name__ == "__main__":
    main()
