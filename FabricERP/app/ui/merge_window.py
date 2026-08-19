# -*- coding: utf-8 -*-
"""数据库合并预览确认窗口。"""

import tkinter as tk
from tkinter import scrolledtext, ttk


class MergePreviewWindow(tk.Toplevel):
    """显示完整计划；只有无冲突且确有新增时才允许确认。"""

    def __init__(self, master, report):
        super().__init__(master)
        self.report = report
        self.result = False
        self.title("合并另一台电脑的数据 — 预览")
        self.geometry("720x580")
        self.minsize(620, 460)
        self.transient(master)

        color = "#1e8449" if report.ok else "#b03a2e"
        title = ("检查通过，可以安全合并" if report.ok
                 else "发现冲突，尚不能合并")
        ttk.Label(self, text=title, foreground=color,
                  font=("Microsoft YaHei UI", 12, "bold"),
                  padding=(14, 12, 14, 6)).pack(anchor="w")

        text = scrolledtext.ScrolledText(
            self, wrap="word", font=("Microsoft YaHei UI", 10),
            padx=10, pady=8)
        text.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        text.insert("1.0", report.text())
        text.configure(state="disabled")

        if report.ok:
            ttk.Label(
                self, foreground="#8a5a00", wraplength=680, justify="left",
                text="合并只会新增缺少的数据，不会覆盖服务器。执行前将自动备份。",
                padding=(14, 0, 14, 4)).pack(anchor="w")

        buttons = ttk.Frame(self, padding=(14, 8, 14, 14))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="取消" if report.ok else "关闭",
                   command=self._cancel).pack(side="right")
        if report.ok and report.total_added:
            ttk.Button(buttons, text="确认合并", style="Accent.TButton",
                       command=self._confirm).pack(side="right", padx=(0, 8))

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.grab_set()
        self.wait_window(self)

    def _confirm(self):
        self.result = True
        self.destroy()

    def _cancel(self):
        self.result = False
        self.destroy()
