import tkinter as tk
from tkinter import font as tkfont


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
        self._saved_geometry = None

        self.root = tk.Tk()
        self.root.title("实时中文字幕")
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", self.ALPHA_LEVELS[self._alpha_index])
        self.root.configure(bg="#0a0a0a")
        self.root.geometry("960x260+120+120")
        self.root.minsize(self.MIN_WIDTH, self.MIN_HEIGHT)

        # macOS-native frameless window that still receives keyboard events.
        # Falls back to overrideredirect on other platforms.
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

        # Traffic-light controls (close / min / max) at top-left.
        self.controls = tk.Canvas(
            self.root,
            width=64,
            height=18,
            bg="#0a0a0a",
            bd=0,
            highlightthickness=0,
        )
        self.controls.pack(anchor="w", padx=12, pady=(8, 0))

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
        # Allow dragging the window by grabbing empty canvas space.
        self.controls.bind("<ButtonPress-1>", self._on_press)
        self.controls.bind("<B1-Motion>", self._on_drag)

        self.content = tk.Text(
            self.root,
            bg="#0a0a0a",
            fg="#ffffff",
            bd=0,
            highlightthickness=0,
            wrap="word",
            padx=20,
            pady=6,
            cursor="hand2",
        )
        self.content.pack(fill="both", expand=True)

        self.content.tag_configure("orig", font=self.orig_font, foreground="#bbbbbb")
        self.content.tag_configure("zh", font=self.zh_font, foreground="#ffffff")
        for i, color in enumerate(SPEAKER_COLORS):
            self.content.tag_configure(f"speaker_{i}", font=self.speaker_font, foreground=color)

        self.content.configure(state="disabled")

        self.status_var = tk.StringVar(value="● 未开始")
        self.status = tk.Label(
            self.root,
            textvariable=self.status_var,
            font=self.status_font,
            fg="#777777",
            bg="#0a0a0a",
            anchor="w",
        )
        self.status.pack(fill="x", padx=20, pady=(0, 10))

        # Resize grip at bottom-right corner.
        self.grip = tk.Label(
            self.root,
            text="◢",
            font=self.grip_font,
            fg="#666666",
            bg="#0a0a0a",
            cursor="bottom_right_corner",
        )
        self.grip.place(relx=1.0, rely=1.0, anchor="se", x=-4, y=-2)
        self.grip.bind("<ButtonPress-1>", self._on_grip_press)
        self.grip.bind("<B1-Motion>", self._on_grip_drag)
        self.grip.bind("<Enter>", lambda e: self.grip.configure(fg="#cccccc"))
        self.grip.bind("<Leave>", lambda e: self.grip.configure(fg="#666666"))

        # Drag-to-move on everything EXCEPT grip and traffic-light buttons.
        for w in (self.root, self.content, self.status):
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
            event.x_root,
            event.y_root,
            self.root.winfo_width(),
            self.root.winfo_height(),
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
        # Shrink to a compact strip showing only the traffic-light row.
        # Click the yellow button again (or anywhere on the strip) to restore.
        if self._maximized:
            self._on_max_btn(None)  # un-maximize first
        if not getattr(self, "_minimized", False):
            self._pre_min_geometry = self.root.geometry()
            cur_w = self.root.winfo_width()
            self.root.geometry(f"{min(cur_w, 260)}x30")
            self._minimized = True
        else:
            self.root.geometry(self._pre_min_geometry)
            self._minimized = False
        return "break"

    def _on_max_btn(self, event):
        if getattr(self, "_minimized", False):
            # restore from minimized first
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
