"""全局库存窗口：跨客户查所有在库缸号。"""

import tkinter as tk
from tkinter import messagebox, ttk

from .. import services
from .widgets import ReadonlyGrid, fmt_meters, setup_style

COLS = [
    {"key": "customer", "title": "客户", "width": 150, "anchor": "w"},
    {"key": "in_date", "title": "进仓日期", "width": 95},
    {"key": "dye_lot", "title": "缸号", "width": 100},
    {"key": "fabric", "title": "面料名称", "width": 165, "anchor": "w"},
    {"key": "color", "title": "颜色", "width": 90},
    {"key": "in_rolls", "title": "进仓卷", "width": 62, "anchor": "e"},
    {"key": "in_meters", "title": "进仓米", "width": 85, "anchor": "e"},
    {"key": "greige_rolls", "title": "未加工卷", "width": 72, "anchor": "e"},
    {"key": "greige_meters", "title": "未加工米", "width": 88, "anchor": "e"},
    {"key": "fin_rolls", "title": "待发卷", "width": 62, "anchor": "e"},
    {"key": "fin_meters", "title": "待发米", "width": 85, "anchor": "e"},
    {"key": "out_rolls", "title": "已发卷", "width": 62, "anchor": "e"},
    {"key": "out_meters", "title": "已发米", "width": 85, "anchor": "e"},
    {"key": "state", "title": "状态", "width": 80, "stretch": True},
]


class StockWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("全局库存")
        self.geometry("1220x560")
        setup_style(self)
        self.transient(master)

        bar = ttk.Frame(self, padding=(10, 10, 10, 6))
        bar.pack(fill="x")
        ttk.Label(bar, text="搜索（客户/缸号/面料/颜色）：").pack(side="left")
        self.kw = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.kw, width=24)
        e.pack(side="left", padx=4)
        e.bind("<KeyRelease>", lambda _: self.refresh())

        self.only_open = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="只看未发完", variable=self.only_open,
                        command=self.refresh).pack(side="left", padx=12)
        ttk.Button(bar, text="导出 Excel", command=self.export).pack(side="right")

        self.grid = ReadonlyGrid(self, COLS)
        self.grid.pack(fill="both", expand=True, padx=10)

        self.total = ttk.Label(self, text="", style="Total.TLabel", anchor="e",
                               padding=(12, 8))
        self.total.pack(fill="x")
        self.refresh()
        e.focus_set()

    def refresh(self):
        self.rows = services.global_stock(self.kw.get().strip(), self.only_open.get())
        self.grid.load(self.rows, lambda r: (
            r["customer"], r["in_date"], r["dye_lot"], r["fabric"], r["color"],
            r["in_rolls"], fmt_meters(r["in_meters"]),
            r["greige_rolls"], fmt_meters(r["greige_meters"]),
            r["fin_rolls"], fmt_meters(r["fin_meters"]),
            r["out_rolls"], fmt_meters(r["out_meters"]), r["state"]),
            lambda r: "warn" if services.is_shrink_abnormal(r["shrink_pct"]) else None)
        self.total.config(
            text=f"共 {len(self.rows)} 个缸号　|　未加工坯布 "
                 f"{sum(r['greige_rolls'] for r in self.rows)} 卷 "
                 f"{fmt_meters(sum(r['greige_meters'] for r in self.rows))} 米"
                 f"　|　已加工待发 {sum(r['fin_rolls'] for r in self.rows)} 卷 "
                 f"{fmt_meters(sum(r['fin_meters'] for r in self.rows))} 米")

    def export(self):
        from ..export import excel
        path = excel.export_stock(self.rows, parent=self)
        if path:
            messagebox.showinfo("导出完成", f"已导出到：\n{path}", parent=self)
