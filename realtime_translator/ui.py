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

        self.root = tk.Tk()
        self.root.title("实时中文字幕")
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", self.ALPHA_LEVELS[self._alpha_index])
        self.root.configure(bg="#0a0a0a")
        self.root.geometry("960x240+120+120")
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

        self.content = tk.Text(
            self.root,
            bg="#0a0a0a",
            fg="#ffffff",
            bd=0,
            highlightthickness=0,
            wrap="word",
            padx=20,
            pady=12,
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

        # Drag-to-move on everything EXCEPT the grip.
        for w in (self.root, self.content, self.status):
            w.bind("<ButtonPress-1>", self._on_press)
            w.bind("<B1-Motion>", self._on_drag)

        self.root.bind_all("<Command-t>", lambda e: self._cycle_alpha())
        self.root.bind_all("<Command-T>", lambda e: self._cycle_alpha())
        self.root.bind_all("<Command-q>", lambda e: self._quit())
        self.root.bind_all("<Command-Q>", lambda e: self._quit())
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
        self.status_var.set(f"{text}   ⌘T 透明度  ⌘Q 退出  拖拽移动  右下角◢调尺寸")

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
