"""对账单 Tab：期初 + 本期应收 - 本期已收 = 期末应收。"""

import tkinter as tk
from tkinter import messagebox, ttk

from .. import models, services
from .widgets import (DateEntry, FONT_BOLD, ReadonlyGrid, fmt_meters, fmt_money,
                      month_range)

COLS = [
    {"key": "ship_date", "title": "日期", "width": 95},
    {"key": "doc_no", "title": "送货单号", "width": 125},
    {"key": "dye_lot", "title": "缸号", "width": 95},
    {"key": "fabric", "title": "面料名称", "width": 155, "anchor": "w"},
    {"key": "color", "title": "颜色", "width": 85},
    {"key": "process", "title": "工艺", "width": 100},
    {"key": "rolls", "title": "卷数", "width": 60, "anchor": "e"},
    {"key": "meters", "title": "米数", "width": 95, "anchor": "e"},
    {"key": "unit_price", "title": "单价", "width": 70, "anchor": "e"},
    {"key": "amount", "title": "金额", "width": 110, "anchor": "e", "stretch": True},
]

PAY_COLS = [
    {"key": "pay_date", "title": "日期", "width": 95},
    {"key": "amount", "title": "收款金额", "width": 110, "anchor": "e"},
    {"key": "method", "title": "方式", "width": 80},
    {"key": "ref_no", "title": "凭证号", "width": 150, "anchor": "w"},
    {"key": "note", "title": "备注", "width": 200, "anchor": "w", "stretch": True},
]


class StatementTab(ttk.Frame):
    def __init__(self, master, win):
        super().__init__(master, padding=8)
        self.win = win
        self.cid = win.customer_id
        self.data = None

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(bar, text="对账区间：").pack(side="left")
        f, t = month_range()
        self.d1 = DateEntry(bar, f, width=11)
        self.d1.pack(side="left")
        ttk.Label(bar, text="~").pack(side="left", padx=3)
        self.d2 = DateEntry(bar, t, width=11)
        self.d2.pack(side="left")
        ttk.Button(bar, text="查询", command=self.refresh).pack(side="left", padx=6)
        ttk.Button(bar, text="本月", command=lambda: self._set_month(0)).pack(side="left")
        ttk.Button(bar, text="上月", command=lambda: self._set_month(-1)).pack(side="left", padx=4)
        ttk.Button(bar, text="全部", command=self._all).pack(side="left")

        ttk.Button(bar, text="打印对账单", command=self.do_print).pack(side="right")
        ttk.Button(bar, text="导出 Excel", command=self.do_export).pack(side="right", padx=6)

        # 汇总卡片
        card = ttk.Frame(self, padding=(10, 8), relief="groove", borderwidth=1)
        card.pack(fill="x", pady=(0, 8))
        self.lbl = {}
        for i, (key, text) in enumerate([("opening", "期初欠款"), ("billed", "本期应收"),
                                         ("paid", "本期已收"), ("closing", "期末应收")]):
            box = ttk.Frame(card)
            box.grid(row=0, column=i, padx=24, sticky="w")
            ttk.Label(box, text=text, foreground="#666").pack(anchor="w")
            v = ttk.Label(box, text="0.00", font=("Microsoft YaHei UI", 15, "bold"))
            v.pack(anchor="w")
            self.lbl[key] = v
            if i < 3:
                ttk.Label(card, text="＋" if i == 0 else ("－" if i == 1 else "＝"),
                          font=FONT_BOLD, foreground="#888").grid(row=0, column=i, padx=(0, 0),
                                                                  sticky="e")
        self.lbl["closing"].configure(foreground="#c00000")

        panes = ttk.PanedWindow(self, orient="vertical")
        panes.pack(fill="both", expand=True)
        top, bot = ttk.Frame(panes), ttk.Frame(panes)
        panes.add(top, weight=3)
        panes.add(bot, weight=1)

        ttk.Label(top, text="本期发货明细", padding=(2, 2)).pack(anchor="w")
        self.grid = ReadonlyGrid(top, COLS)
        self.grid.pack(fill="both", expand=True)

        ttk.Label(bot, text="本期收款记录", padding=(2, 4)).pack(anchor="w")
        self.pays = ReadonlyGrid(bot, PAY_COLS)
        self.pays.pack(fill="both", expand=True)

    def _set_month(self, off):
        f, t = month_range(off)
        self.d1.set(f)
        self.d2.set(t)
        self.refresh()

    def _all(self):
        self.d1.set("")
        self.d2.set("")
        self.refresh()

    def refresh(self):
        try:
            f, t = self.d1.get(), self.d2.get()
        except ValueError as e:
            messagebox.showwarning("日期有误", str(e), parent=self.win)
            return
        st = services.statement(self.cid, f, t)
        self.data = st

        for k in ("opening", "billed", "paid", "closing"):
            self.lbl[k].config(text=fmt_money(st[k]))

        self.grid.load(st["items"], lambda r: (
            r["ship_date"], r["doc_no"], r["dye_lot"], r["fabric"], r["color"],
            r["process"], r["rolls"], fmt_meters(r["meters"]),
            f"{r['unit_price']:g}", fmt_money(r["amount"])))
        if st["items"]:
            self.grid.append_total(("合计", "", "", f"{len(st['items'])} 行", "", "",
                                    st["total_rolls"], fmt_meters(st["total_meters"]),
                                    "", fmt_money(st["billed"])))

        self.pays.load(st["payments"], lambda r: (
            r["pay_date"], fmt_money(r["amount"]), r["method"],
            r["ref_no"] or "", r["note"] or ""))
        if st["payments"]:
            self.pays.append_total(("合计", fmt_money(st["paid"]), "", "", ""))

    def do_print(self):
        if not self.data:
            self.refresh()
        from ..export import printing
        printing.print_statement(self.data)

    def do_export(self):
        if not self.data:
            self.refresh()
        from ..export import excel
        path = excel.export_statement(self.data, parent=self.win)
        if path:
            messagebox.showinfo("导出完成", f"已导出到：\n{path}", parent=self.win)
