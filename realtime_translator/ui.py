import tkinter as tk
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

LOGO_PATH = Path(__file__).resolve().parent / "assets" / "logo.png"
BG_COLOR = "#0a0a0a"


def _load_logo(size, alpha=1.0, bg_rgb=(10, 10, 10)):
    """Load logo.png, resize to ``size`` px, optionally fade onto the BG color.

    Fading by pre-compositing onto the window background color is required
    because Tk Label widgets don't render per-pixel alpha transparency —
    they paint a solid bg behind the image. For a watermark effect we blend
    the logo against the known dark bg before handing it to Tk.
    """
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


class SubtitleWindow:
    """Frameless, translucent, always-on-top subtitle window."""

    ALPHA_LEVELS = (0.5, 0.8, 1.0)
    MIN_WIDTH = 400
    MIN_HEIGHT = 140

    def __init__(self, max_lines=4):
        self.max_lines = max_lines
        self._entries = []  # list of (speaker_id, original, translation)
        self._alpha_index = 1  # default 0.8
        self._close_callback = None
        self._maximized = False
        self._minimized = False
        self._saved_geometry = None
        self._pre_min_geometry = None

        self.root = tk.Tk()
        self.root.title("实时中文字幕")
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", self.ALPHA_LEVELS[self._alpha_index])
        self.root.configure(bg=BG_COLOR)
        self.root.geometry("960x260+120+120")
        self.root.minsize(self.MIN_WIDTH, self.MIN_HEIGHT)

        try:
            self.root.tk.call(
                "::tk::unsupported::MacWindowStyle", "style",
                self.root._w, "plain", "none",
            )
        except tk.TclError:
            self.root.overrideredirect(True)

        family = self._pick_font_family()
        self.orig_font = tkfont.Font(family=family, size=15)
        self.zh_font = tkfont.Font(family=family, size=22, weight="bold")
        self.speaker_font = tkfont.Font(family=family, size=22, weight="bold")
        self.status_font = tkfont.Font(family=family, size=11)
        self.grip_font = tkfont.Font(family=family, size=13)

        self._logo_small = _load_logo(22)
        self._logo_watermark = _load_logo(90, alpha=0.18)

        # === Top bar: traffic lights on the left, small logo on the right ===
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

        if self._logo_small:
            self.logo_label = tk.Label(top_bar, image=self._logo_small, bg=BG_COLOR, bd=0)
            self.logo_label.pack(side="right", padx=(0, 2))
            self.logo_label.bind("<ButtonPress-1>", self._on_press)
            self.logo_label.bind("<B1-Motion>", self._on_drag)
        else:
            self.logo_label = None

        # === Main content ===
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

        # === Status bar: status text (left) + session cost (right) ===
        self.status_var = tk.StringVar(value="● 未开始")
        self.cost_var = tk.StringVar(value="")

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

        # === Watermark (bottom-right, faded) ===
        if self._logo_watermark:
            self.watermark = tk.Label(self.root, image=self._logo_watermark, bg=BG_COLOR, bd=0)
            self.watermark.place(relx=1.0, rely=1.0, anchor="se", x=-12, y=-40)
        else:
            self.watermark = None

        # === Resize grip (bottom-right corner) ===
        self.grip = tk.Label(
            self.root, text="◢", font=self.grip_font,
            fg="#666666", bg=BG_COLOR, cursor="bottom_right_corner",
        )
        self.grip.place(relx=1.0, rely=1.0, anchor="se", x=-4, y=-2)
        self.grip.bind("<ButtonPress-1>", self._on_grip_press)
        self.grip.bind("<B1-Motion>", self._on_grip_drag)
        self.grip.bind("<Enter>", lambda e: self.grip.configure(fg="#cccccc"))
        self.grip.bind("<Leave>", lambda e: self.grip.configure(fg="#666666"))

        # Drag-to-move on everything except grip and traffic-light buttons.
        for w in (self.root, self.content, self.status, status_bar, self.cost_label):
            w.bind("<ButtonPress-1>", self._on_press)
            w.bind("<B1-Motion>", self._on_drag)

        self.root.bind_all("<Command-t>", lambda e: self._cycle_alpha())
        self.root.bind_all("<Command-T>", lambda e: self._cycle_alpha())
        self.root.bind_all("<Command-q>", lambda e: self._quit())
        self.root.bind_all("<Command-Q>", lambda e: self._quit())
        self.root.bind_all("<Command-m>", lambda e: self._on_min_btn(None))
        self.root.bind_all("<Command-M>", lambda e: self._on_min_btn(None))
        self.root.bind_all("<Escape>", lambda e: self._quit())

        self.root.after(50, self._force_focus)

    def _force_focus(self):
        try:
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

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

    def append_line(self, speaker_id, original, translation):
        original = (original or "").strip()
        translation = (translation or "").strip()
        if not original and not translation:
            return
        self._entries.append((speaker_id, original, translation))
        if len(self._entries) > self.max_lines:
            self._entries = self._entries[-self.max_lines:]
        self._render()

    def _render(self):
        self.content.configure(state="normal")
        self.content.delete("1.0", "end")
        for idx, (speaker_id, original, translation) in enumerate(self._entries):
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
        self.content.see("end")

    def set_status(self, text):
        self.status_var.set(f"{text}   ⌘T 透明度  ⌘M 最小化  ⌘Q 退出")

    def set_cost(self, text):
        self.cost_var.set(text)

    def after(self, ms, callback):
        return self.root.after(ms, callback)

    def on_close(self, callback):
        self._close_callback = callback
        self.root.protocol("WM_DELETE_WINDOW", callback)

    def run(self):
        self.root.mainloop()

    def destroy(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass
