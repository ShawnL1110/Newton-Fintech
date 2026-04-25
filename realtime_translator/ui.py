import random
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import font as tkfont

try:
    from PIL import Image, ImageTk
    _PIL_OK = True
except Exception:
    _PIL_OK = False


SPEAKER_COLORS = [
    "#4ec9b0",  # teal
    "#ffb86c",  # orange
    "#bd93f9",  # purple
    "#8be9fd",  # cyan
    "#50fa7b",  # green
    "#ff79c6",  # pink
    "#f1fa8c",  # yellow
    "#ff5555",  # red
]

ENGINE_MENU_LABELS = [
    ("batch",    "OpenAI (标准)"),
    ("realtime", "OpenAI Realtime (低延迟)"),
    ("mixed",    "混合 (本地转写 + OpenAI 翻译)"),
    ("live",     "同传 Live (强制 3s commit)"),
]

LOGO_PATH = Path(__file__).resolve().parent / "assets" / "logo.png"
BG_COLOR = "#0a0a0a"


def _load_logo(size, alpha=1.0, bg_rgb=(10, 10, 10)):
    if not _PIL_OK or not LOGO_PATH.exists():
        return None
    try:
        img = Image.open(LOGO_PATH).convert("RGBA")
        img.thumbnail((size, size), Image.LANCZOS)
        if alpha < 1.0:
            r, g, b, a = img.split()
            faded_alpha = a.point(lambda x: int(x * alpha))
            bg = Image.new("RGBA", img.size, bg_rgb + (255,))
            img.putalpha(faded_alpha)
            img = Image.alpha_composite(bg, img)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None


def _format_duration(seconds):
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _set_ns_window_level(elevated):
    """Raise/restore our NSWindow level (macOS, requires pyobjc).

    Elevated uses NSScreenSaverWindowLevel (1000) — high enough to sit on
    top of fullscreen-space apps for a karaoke / song-lyrics effect.
    Restored uses NSNormalWindowLevel (0).

    Silently no-ops when pyobjc isn't installed.
    """
    try:
        from AppKit import (
            NSApp,
            NSNormalWindowLevel,
            NSScreenSaverWindowLevel,
        )
        if elevated:
            level = NSScreenSaverWindowLevel
            behavior = (1 << 0) | (1 << 8)  # CanJoinAllSpaces | FullScreenAuxiliary
        else:
            level = NSNormalWindowLevel
            behavior = 0
        for window in NSApp.windows():
            try:
                window.setLevel_(level)
                window.setCollectionBehavior_(behavior)
            except Exception:
                pass
    except Exception:
        pass


def _round_window_corners(radius=12.0):
    """Add rounded corners to our NSWindow's content view (macOS, pyobjc).

    Layer-backs the contentView and applies a corner mask. To make the
    rounded edges actually transparent we also clear the NSWindow's own
    background — Tk widgets keep painting their dark fill, so the visible
    rectangle stays solid; only the outside-the-radius pixels become
    see-through.
    """
    try:
        from AppKit import NSApp, NSColor
        for window in NSApp.windows():
            try:
                content_view = window.contentView()
                if content_view is None:
                    continue
                content_view.setWantsLayer_(True)
                layer = content_view.layer()
                if layer is not None:
                    layer.setCornerRadius_(float(radius))
                    layer.setMasksToBounds_(True)
                window.setOpaque_(False)
                window.setBackgroundColor_(NSColor.clearColor())
                window.setHasShadow_(True)
            except Exception:
                pass
    except Exception:
        pass


class WaveformWidget:
    """A row of bars that pulse with an externally-supplied audio level."""

    BAR_COUNT = 10
    BAR_WIDTH = 3
    BAR_GAP = 3
    MAX_HEIGHT = 14
    MIN_HEIGHT = 2
    COLORS = [
        "#4ec9b0", "#52c9b4", "#56c9b8", "#5ac9bc", "#5ec9bf",
        "#52cfb8", "#46d5b0", "#50db9e", "#5ae18c", "#65e17a",
    ]

    def __init__(self, parent, tick_ms=50, bg=BG_COLOR):
        self.tick_ms = tick_ms
        total_w = self.BAR_COUNT * (self.BAR_WIDTH + self.BAR_GAP) - self.BAR_GAP
        total_h = self.MAX_HEIGHT + 4
        self.canvas = tk.Canvas(
            parent, width=total_w, height=total_h,
            bg=bg, bd=0, highlightthickness=0,
        )
        self._heights = [float(self.MIN_HEIGHT)] * self.BAR_COUNT
        self._bars = []
        center_y = total_h / 2
        for i in range(self.BAR_COUNT):
            x = i * (self.BAR_WIDTH + self.BAR_GAP)
            h = self._heights[i]
            bar = self.canvas.create_rectangle(
                x, center_y - h / 2, x + self.BAR_WIDTH, center_y + h / 2,
                fill=self.COLORS[i % len(self.COLORS)], outline="",
            )
            self._bars.append((bar, x, center_y))
        self._level_provider = lambda: 0.0
        self._rng = random.Random(42)
        self._animating = False

    def pack(self, **kw):
        self.canvas.pack(**kw)

    def bind(self, seq, handler):
        self.canvas.bind(seq, handler)

    def set_level_provider(self, provider):
        self._level_provider = provider

    def start(self):
        if not self._animating:
            self._animating = True
            self._tick()

    def stop(self):
        self._animating = False

    def _tick(self):
        if not self._animating:
            return
        try:
            level = float(self._level_provider() or 0.0)
        except Exception:
            level = 0.0
        scaled = min(1.0, level * 6.0)
        range_h = self.MAX_HEIGHT - self.MIN_HEIGHT

        for i, (bar_id, x, cy) in enumerate(self._bars):
            jitter = 0.45 + self._rng.random() * 0.55
            target = self.MIN_HEIGHT + scaled * jitter * range_h
            new_h = max(target, self._heights[i] * 0.82)
            if new_h < self.MIN_HEIGHT:
                new_h = self.MIN_HEIGHT
            self._heights[i] = new_h
            try:
                self.canvas.coords(
                    bar_id, x, cy - new_h / 2, x + self.BAR_WIDTH, cy + new_h / 2,
                )
            except tk.TclError:
                return

        try:
            self.canvas.after(self.tick_ms, self._tick)
        except tk.TclError:
            pass


class SubtitleWindow:
    """Frameless, translucent, always-on-top subtitle window."""

    ALPHA_LEVELS = (0.5, 0.8, 1.0)
    MIN_WIDTH = 400
    MIN_HEIGHT = 140

    def __init__(self, max_lines=4):
        self.max_lines = max_lines
        # Full transcript: (timestamp, speaker_id, original, translation).
        self._entries = []
        # When the tail entry is a streaming partial from realtime mode, the
        # next append_line call replaces it in place instead of appending.
        self._streaming_tail = False
        self._session_start = time.time()
        self._alpha_index = 1
        self._close_callback = None
        self._engine_change_callback = None
        self._pause_callback = None
        self._maximized = False
        self._minimized = False
        self._saved_geometry = None
        self._pre_min_geometry = None
        # Overlay-above-fullscreen state (toggle via ⌘⇧F).
        self._fullscreen_overlay = True

        self.root = tk.Tk()
        self.root.title("实时中文字幕")
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", self.ALPHA_LEVELS[self._alpha_index])
        self.root.configure(bg=BG_COLOR)
        self.root.geometry("960x260+120+120")
        self.root.minsize(self.MIN_WIDTH, self.MIN_HEIGHT)

        self.root.overrideredirect(True)
        # Apply once on startup, then keep re-applying every few seconds in
        # case macOS resets the level when the active Space changes.
        self.root.after(100, lambda: _set_ns_window_level(self._fullscreen_overlay))
        self.root.after(150, lambda: _round_window_corners(12.0))
        self.root.after(3000, self._reapply_window_level_loop)

        family = self._pick_font_family()
        self.orig_font = tkfont.Font(family=family, size=15)
        self.zh_font = tkfont.Font(family=family, size=22, weight="bold")
        self.speaker_font = tkfont.Font(family=family, size=22, weight="bold")
        self.status_font = tkfont.Font(family=family, size=11)
        self.button_font = tkfont.Font(family=family, size=13)
        self.grip_font = tkfont.Font(family=family, size=13)

        self._logo_small = _load_logo(22)

        top_bar = tk.Frame(self.root, bg=BG_COLOR)
        top_bar.pack(fill="x", padx=12, pady=(8, 0))

        self.controls = tk.Canvas(
            top_bar, width=64, height=18, bg=BG_COLOR, bd=0, highlightthickness=0,
        )
        self.controls.pack(side="left")

        btn_size = 14
        gap = 8
        self._btn_close = self.controls.create_oval(
            0, 2, btn_size, btn_size + 2, fill="#ff5f57", outline=""
        )
        self._btn_min = self.controls.create_oval(
            btn_size + gap, 2, btn_size * 2 + gap, btn_size + 2,
            fill="#febc2e", outline="",
        )
        self._btn_max = self.controls.create_oval(
            btn_size * 2 + gap * 2, 2, btn_size * 3 + gap * 2, btn_size + 2,
            fill="#28c840", outline="",
        )
        for item, handler in (
            (self._btn_close, self._on_close_btn),
            (self._btn_min, self._on_min_btn),
            (self._btn_max, self._on_max_btn),
        ):
            self.controls.tag_bind(item, "<Button-1>", handler)
            self.controls.tag_bind(item, "<Enter>",
                                   lambda e: self.controls.configure(cursor="hand2"))
            self.controls.tag_bind(item, "<Leave>",
                                   lambda e: self.controls.configure(cursor=""))
        self.controls.bind("<ButtonPress-1>", self._on_press)
        self.controls.bind("<B1-Motion>", self._on_drag)

        self.waveform = WaveformWidget(top_bar)
        self.waveform.pack(side="left", padx=(16, 0))
        self.waveform.bind("<ButtonPress-1>", self._on_press)
        self.waveform.bind("<B1-Motion>", self._on_drag)

        if self._logo_small:
            self.logo_label = tk.Label(top_bar, image=self._logo_small, bg=BG_COLOR, bd=0)
            self.logo_label.pack(side="right", padx=(0, 2))
            self.logo_label.bind("<ButtonPress-1>", self._on_press)
            self.logo_label.bind("<B1-Motion>", self._on_drag)
        else:
            self.logo_label = None

        self.content = tk.Text(
            self.root, bg=BG_COLOR, fg="#ffffff", bd=0, highlightthickness=0,
            wrap="word", padx=20, pady=6, cursor="hand2",
        )
        self.content.pack(fill="both", expand=True)

        self.content.tag_configure("orig", font=self.orig_font, foreground="#bbbbbb")
        self.content.tag_configure("zh", font=self.zh_font, foreground="#ffffff")
        for i, color in enumerate(SPEAKER_COLORS):
            self.content.tag_configure(f"speaker_{i}", font=self.speaker_font, foreground=color)
        self.content.configure(state="disabled")

        self.status_var = tk.StringVar(value="● 未开始")
        self.cost_var = tk.StringVar(value="")
        self._engine_var = tk.StringVar(value="batch")

        status_bar = tk.Frame(self.root, bg=BG_COLOR)
        status_bar.pack(fill="x", padx=20, pady=(0, 10))

        self.status = tk.Label(
            status_bar, textvariable=self.status_var, font=self.status_font,
            fg="#777777", bg=BG_COLOR, anchor="w",
        )
        self.status.pack(side="left", fill="x", expand=True)

        self.cost_label = tk.Label(
            status_bar, textvariable=self.cost_var, font=self.status_font,
            fg="#8ab4a0", bg=BG_COLOR, anchor="e",
        )
        self.cost_label.pack(side="right")

        self.save_button = tk.Label(
            status_bar, text="💾", font=self.button_font,
            fg="#888888", bg=BG_COLOR, cursor="hand2",
        )
        self.save_button.pack(side="right", padx=(0, 10))
        self.save_button.bind("<Button-1>", lambda e: self.save_history())
        self.save_button.bind("<Enter>", lambda e: self.save_button.configure(fg="#ffffff"))
        self.save_button.bind("<Leave>", lambda e: self.save_button.configure(fg="#888888"))

        self.gear_button = tk.Label(
            status_bar, text="⚙", font=self.button_font,
            fg="#888888", bg=BG_COLOR, cursor="hand2",
        )
        self.gear_button.pack(side="right", padx=(0, 8))
        self.gear_button.bind("<Button-1>", self._show_engine_menu)
        self.gear_button.bind("<Enter>", lambda e: self.gear_button.configure(fg="#ffffff"))
        self.gear_button.bind("<Leave>", lambda e: self.gear_button.configure(fg="#888888"))

        self.grip = tk.Label(
            self.root, text="◢", font=self.grip_font,
            fg="#666666", bg=BG_COLOR, cursor="bottom_right_corner",
        )
        self.grip.place(relx=1.0, rely=1.0, anchor="se", x=-4, y=-2)
        self.grip.bind("<ButtonPress-1>", self._on_grip_press)
        self.grip.bind("<B1-Motion>", self._on_grip_drag)
        self.grip.bind("<Enter>", lambda e: self.grip.configure(fg="#cccccc"))
        self.grip.bind("<Leave>", lambda e: self.grip.configure(fg="#666666"))

        for w in (self.root, self.content, self.status, status_bar, self.cost_label):
            w.bind("<ButtonPress-1>", self._on_press)
            w.bind("<B1-Motion>", self._on_drag)

        self.root.bind_all("<Command-t>", lambda e: self._cycle_alpha())
        self.root.bind_all("<Command-T>", lambda e: self._cycle_alpha())
        self.root.bind_all("<Command-q>", lambda e: self._quit())
        self.root.bind_all("<Command-Q>", lambda e: self._quit())
        self.root.bind_all("<Command-m>", lambda e: self._on_min_btn(None))
        self.root.bind_all("<Command-M>", lambda e: self._on_min_btn(None))
        self.root.bind_all("<Command-s>", lambda e: self.save_history())
        self.root.bind_all("<Command-S>", lambda e: self.save_history())
        self.root.bind_all("<Command-Shift-f>", lambda e: self._toggle_fullscreen_overlay())
        self.root.bind_all("<Command-Shift-F>", lambda e: self._toggle_fullscreen_overlay())
        # Spacebar pauses/resumes translation (engine-level pause).
        # ⌘P is provided as a backup since some focus states swallow space.
        self.root.bind_all("<space>", lambda e: self._toggle_pause())
        self.root.bind_all("<Command-p>", lambda e: self._toggle_pause())
        self.root.bind_all("<Command-P>", lambda e: self._toggle_pause())
        self.root.bind_all("<Escape>", lambda e: self._quit())

        self.root.after(50, self._force_focus)
        self.waveform.start()

    def _force_focus(self):
        try:
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

    def _reapply_window_level_loop(self):
        # macOS sometimes resets window level when the active Space changes
        # (e.g. when an app enters fullscreen). Re-applying every 3s keeps
        # the overlay sticky.
        if self._fullscreen_overlay:
            _set_ns_window_level(True)
        try:
            self.root.after(3000, self._reapply_window_level_loop)
        except tk.TclError:
            pass

    def _toggle_fullscreen_overlay(self):
        self._fullscreen_overlay = not self._fullscreen_overlay
        _set_ns_window_level(self._fullscreen_overlay)
        msg = "✓ 浮顶已开启 (盖在全屏应用上)" if self._fullscreen_overlay else "○ 浮顶已关闭"
        self.status_var.set(msg)

    @staticmethod
    def _pick_font_family():
        available = set(tkfont.families())
        for name in ("PingFang SC", "Heiti SC", "Hiragino Sans GB", "STHeiti", "Helvetica"):
            if name in available:
                return name
        return "TkDefaultFont"

    def _on_press(self, event):
        self._drag_origin = (
            event.x_root - self.root.winfo_x(),
            event.y_root - self.root.winfo_y(),
        )

    def _on_drag(self, event):
        x = event.x_root - self._drag_origin[0]
        y = event.y_root - self._drag_origin[1]
        self.root.geometry(f"+{x}+{y}")

    def _on_grip_press(self, event):
        self._resize_origin = (
            event.x_root, event.y_root,
            self.root.winfo_width(), self.root.winfo_height(),
        )
        return "break"

    def _on_grip_drag(self, event):
        start_x, start_y, start_w, start_h = self._resize_origin
        dw = event.x_root - start_x
        dh = event.y_root - start_y
        new_w = max(self.MIN_WIDTH, start_w + dw)
        new_h = max(self.MIN_HEIGHT, start_h + dh)
        self.root.geometry(f"{new_w}x{new_h}")
        return "break"

    def _cycle_alpha(self):
        self._alpha_index = (self._alpha_index + 1) % len(self.ALPHA_LEVELS)
        self.root.attributes("-alpha", self.ALPHA_LEVELS[self._alpha_index])

    def _on_close_btn(self, event):
        self._quit()
        return "break"

    def _on_min_btn(self, event):
        if self._maximized:
            self._on_max_btn(None)
        if not self._minimized:
            self._pre_min_geometry = self.root.geometry()
            cur_w = self.root.winfo_width()
            self.root.geometry(f"{min(cur_w, 260)}x30")
            self._minimized = True
        else:
            if self._pre_min_geometry:
                self.root.geometry(self._pre_min_geometry)
            self._minimized = False
        return "break"

    def _on_max_btn(self, event):
        if self._minimized:
            if self._pre_min_geometry:
                self.root.geometry(self._pre_min_geometry)
            self._minimized = False
        if not self._maximized:
            self._saved_geometry = self.root.geometry()
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            new_w = int(sw * 0.85)
            new_h = int(sh * 0.35)
            new_x = (sw - new_w) // 2
            new_y = sh - new_h - 120
            self.root.geometry(f"{new_w}x{new_h}+{new_x}+{new_y}")
            self._maximized = True
        else:
            if self._saved_geometry:
                self.root.geometry(self._saved_geometry)
            self._maximized = False
        return "break"

    def _quit(self):
        if self._close_callback:
            self._close_callback()
        else:
            self.destroy()

    def append_line(self, speaker_id, original, translation, is_partial=False):
        """Append or update the transcript tail.

        When ``is_partial`` is False (default), behaves as before: each call
        adds a new entry. When True, the call is treated as a streaming
        update — if the previous call was also partial, we *replace* the
        last entry in place instead of appending. This gives realtime mode
        a live growing-subtitle effect without flooding history with
        intermediate fragments.
        """
        original = (original or "").strip()
        translation = (translation or "").strip()
        if not original and not translation:
            return
        if self._streaming_tail and self._entries:
            prev_ts = self._entries[-1][0]
            self._entries[-1] = (prev_ts, speaker_id, original, translation)
        else:
            self._entries.append((time.time(), speaker_id, original, translation))
        self._streaming_tail = bool(is_partial)
        self._render()

    def _render(self):
        # Stick-to-bottom: only auto-scroll if the user was already viewing
        # the latest content. If they scrolled up to read history, leave
        # their position alone so live updates don't yank them back down.
        try:
            _, bottom_frac = self.content.yview()
            stick_to_bottom = bottom_frac > 0.95
        except (tk.TclError, ValueError):
            stick_to_bottom = True

        self.content.configure(state="normal")
        self.content.delete("1.0", "end")
        for idx, (_ts, speaker_id, original, translation) in enumerate(self._entries):
            color_tag = f"speaker_{speaker_id % len(SPEAKER_COLORS)}"
            label = chr(ord("A") + speaker_id % 26)
            self.content.insert("end", f"[{label}] ", color_tag)
            if original:
                self.content.insert("end", f"{original}\n", "orig")
            if translation:
                self.content.insert("end", f"    {translation}", "zh")
            if idx < len(self._entries) - 1:
                self.content.insert("end", "\n\n")
        self.content.configure(state="disabled")

        if stick_to_bottom:
            self.content.see("end")

    def set_status(self, text):
        self.status_var.set(
            f"{text}   空格/⌘P 暂停  ⌘T 透明度  ⌘⇧F 浮顶  ⌘M 最小化  ⌘S 导出  ⌘Q 退出"
        )

    def set_cost(self, text):
        self.cost_var.set(text)

    def set_level_provider(self, provider):
        self.waveform.set_level_provider(provider)

    def set_engine_change_callback(self, fn):
        self._engine_change_callback = fn

    def set_pause_callback(self, fn):
        """Register a no-arg callable invoked when the user toggles pause."""
        self._pause_callback = fn

    def _toggle_pause(self):
        if self._pause_callback:
            self._pause_callback()

    def set_current_engine(self, engine):
        self._engine_var.set(engine)

    def _show_engine_menu(self, event=None):
        menu = tk.Menu(self.root, tearoff=0)
        for value, label in ENGINE_MENU_LABELS:
            menu.add_radiobutton(
                label=label,
                variable=self._engine_var,
                value=value,
                command=lambda v=value: self._on_engine_select(v),
            )
        try:
            x = self.gear_button.winfo_rootx()
            y = self.gear_button.winfo_rooty() + self.gear_button.winfo_height() + 4
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _on_engine_select(self, engine):
        if self._engine_change_callback:
            self._engine_change_callback(engine)

    def save_history(self):
        from tkinter import filedialog, messagebox
        if not self._entries:
            messagebox.showinfo("导出字幕", "还没有字幕内容可以导出。")
            return
        default_name = time.strftime("字幕记录-%Y%m%d-%H%M%S.md")
        path = filedialog.asksaveasfilename(
            defaultextension=".md",
            initialfile=default_name,
            filetypes=[("Markdown", "*.md"), ("纯文本", "*.txt"), ("所有文件", "*.*")],
            title="导出字幕记录",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._build_markdown())
        except Exception as e:
            messagebox.showerror("导出失败", str(e))
            return
        self.save_button.configure(text="✓", fg="#50fa7b")
        self.save_button.after(
            2000,
            lambda: self.save_button.configure(text="💾", fg="#888888"),
        )

    def _build_markdown(self):
        lines = []
        start = self._session_start
        last_ts = self._entries[-1][0]
        speakers = sorted({e[1] for e in self._entries})

        lines.append("# 实时字幕记录")
        lines.append("")
        lines.append(f"- **开始时间**: {datetime.fromtimestamp(start).strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"- **时长**: {_format_duration(last_ts - start)}")
        lines.append(f"- **说话人数**: {len(speakers)}")
        lines.append(f"- **条数**: {len(self._entries)}")
        lines.append("")
        lines.append("---")
        lines.append("")

        for ts, speaker_id, original, translation in self._entries:
            rel = ts - start
            label = chr(ord("A") + speaker_id % 26)
            lines.append(f"## [{_format_duration(rel)}] · 说话人 {label}")
            lines.append("")
            if original:
                lines.append(f"**{original}**")
                lines.append("")
            if translation:
                lines.append(f"> {translation}")
                lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("*由「实时中文字幕」生成*")
        lines.append("")
        return "\n".join(lines)

    def after(self, ms, callback):
        return self.root.after(ms, callback)

    def on_close(self, callback):
        self._close_callback = callback
        self.root.protocol("WM_DELETE_WINDOW", callback)

    def run(self):
        self.root.mainloop()

    def destroy(self):
        try:
            self.waveform.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass
