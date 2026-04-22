import tkinter as tk
from tkinter import font as tkfont


class SubtitleWindow:
    """Always-on-top draggable subtitle window that shows Chinese translations."""

    def __init__(self, max_lines=3):
        self.max_lines = max_lines
        self._lines = []

        self.root = tk.Tk()
        self.root.title("实时中文字幕")
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#0a0a0a")
        self.root.geometry("960x180+120+120")
        self.root.minsize(400, 80)

        family = self._pick_font_family()
        self.text_font = tkfont.Font(family=family, size=22, weight="bold")
        self.status_font = tkfont.Font(family=family, size=11)

        self.text_var = tk.StringVar(value="等待音频输入…")
        self.status_var = tk.StringVar(value="● 未开始")

        self.label = tk.Label(
            self.root,
            textvariable=self.text_var,
            font=self.text_font,
            fg="#ffffff",
            bg="#0a0a0a",
            wraplength=920,
            justify="left",
            anchor="w",
        )
        self.label.pack(fill="both", expand=True, padx=20, pady=(16, 4))

        self.status = tk.Label(
            self.root,
            textvariable=self.status_var,
            font=self.status_font,
            fg="#888888",
            bg="#0a0a0a",
            anchor="w",
        )
        self.status.pack(fill="x", padx=20, pady=(0, 10))

        for w in (self.root, self.label, self.status):
            w.bind("<ButtonPress-1>", self._on_press)
            w.bind("<B1-Motion>", self._on_drag)

        self.root.bind("<Configure>", self._on_resize)

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

    def _on_resize(self, event):
        if event.widget is self.root:
            self.label.configure(wraplength=max(200, event.width - 40))

    def append_line(self, text):
        text = text.strip()
        if not text:
            return
        self._lines.append(text)
        if len(self._lines) > self.max_lines:
            self._lines = self._lines[-self.max_lines :]
        self.text_var.set("\n".join(self._lines))

    def set_status(self, text):
        self.status_var.set(text)

    def after(self, ms, callback):
        return self.root.after(ms, callback)

    def on_close(self, callback):
        self.root.protocol("WM_DELETE_WINDOW", callback)

    def run(self):
        self.root.mainloop()

    def destroy(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass
