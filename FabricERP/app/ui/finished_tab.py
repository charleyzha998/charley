"""成品库存 Tab：加工好了、还压在厂里没发的货。

这是「厂里压了多少做好的货」的账 —— 做好了不等于发货，发货了才进对账单。
"""

import tkinter as tk
from tkinter import messagebox, ttk

from .. import models
from .widgets import ReadonlyGrid, fmt_meters

COLS = [
    {"key": "done_date", "title": "加工日期", "width": 92},
    {"key": "dye_lot", "title": "缸号", "width": 92},
    {"key": "fabric", "title": "面料名称", "width": 150, "anchor": "w"},
    {"key": "color", "title": "颜色", "width": 85},
    {"key": "process", "title": "工艺", "width": 100},
    {"key": "done_rolls", "title": "成品卷", "width": 66, "anchor": "e"},
    {"key": "done_meters", "title": "成品米", "width": 88, "anchor": "e"},
    {"key": "out_rolls", "title": "已发卷", "width": 66, "anchor": "e"},
    {"key": "out_meters", "title": "已发米", "width": 88, "anchor": "e"},
    {"key": "left_rolls", "title": "待发卷", "width": 66, "anchor": "e"},
    {"key": "left_meters", "title": "待发米", "width": 88, "anchor": "e"},
    {"key": "state", "title": "状态", "width": 76},
    {"key": "note", "title": "备注", "width": 110, "anchor": "w", "stretch": True},
]


class FinishedTab(ttk.Frame):
    def __init__(self, master, win):
        super().__init__(master, padding=8)
        self.win = win
        self.cid = win.customer_id

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="＋ 登记加工完成", style="Accent.TButton",
                   command=self.new_doc).pack(side="left")
        ttk.Button(bar, text="发货", style="Accent.TButton",
                   command=self.do_ship).pack(side="left", padx=6)
        ttk.Button(bar, text="修改", command=self.edit_doc).pack(side="left")
        ttk.Button(bar, text="删除", command=self.del_doc).pack(side="left", padx=6)
        ttk.Button(bar, text="导出 Excel", command=self.export).pack(side="left", padx=(16, 0))

        self.only_open = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="只看还没发完的", variable=self.only_open,
                        command=self.refresh).pack(side="left", padx=(20, 4))
        ttk.Label(bar, text="搜索：").pack(side="left", padx=(10, 2))
        self.kw = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.kw, width=18)
        e.pack(side="left")
        e.bind("<KeyRelease>", lambda _: self.refresh())

        self.grid = ReadonlyGrid(self, COLS, on_double=lambda r: self.do_ship())
        self.grid.pack(fill="both", expand=True)

        self.total = ttk.Label(self, text="", style="Total.TLabel", anchor="e",
                               padding=(0, 6))
        self.total.pack(fill="x")
        ttk.Label(self, foreground="#666", anchor="w",
                  text="加工好了先登记在这里，发货了才进对账单。"
                       "选中一行点「发货」可以直接开单（双击也行）。").pack(fill="x")

    def refresh(self):
        rows = models.list_finished(self.cid, self.kw.get().strip(),
                                    self.only_open.get())
        self.rows = rows
        self.grid.load(rows, lambda r: (
            r["done_date"], r["dye_lot"], r["fabric"], r["color"], r["process"],
            r["done_rolls"], fmt_meters(r["done_meters"]),
            r["out_rolls"], fmt_meters(r["out_meters"]),
            r["left_rolls"], fmt_meters(r["left_meters"]), r["state"], r["note"]),
            tag_fn=lambda r: "done" if r["state"] == "已发完" else None)
        wait = [r for r in rows if r["state"] in ("待发货", "部分发货")]
        self.total.config(
            text=f"共 {len(rows)} 条加工记录　|　厂里待发 "
                 f"{sum(r['left_rolls'] for r in wait)} 卷 / "
                 f"{fmt_meters(sum(r['left_meters'] for r in wait))} 米")

    # ---------- 动作 ----------

    def export(self):
        if not getattr(self, "rows", None):
            messagebox.showinfo("提示", "当前没有可导出的数据", parent=self.win)
            return
        from ..export import excel
        path = excel.export_finished(self.rows, parent=self.win,
                                     customer=self.win.customer["name"])
        if path:
            messagebox.showinfo("导出完成", f"已导出到：\n{path}", parent=self.win)

    def _pick(self):
        row = self.grid.current()
        if not row:
            messagebox.showinfo("提示", "请先选中一行", parent=self.win)
        return row

    def new_doc(self):
        from .production_form import ProductionForm
        if ProductionForm(self.win, self.cid).result:
            self.win.refresh_all()

    def edit_doc(self):
        row = self._pick()
        if not row:
            return
        from .production_form import ProductionForm
        if ProductionForm(self.win, self.cid, prod_id=row["prod_id"]).result:
            self.win.refresh_all()

    def do_ship(self):
        row = self._pick()
        if not row:
            return
        if row["state"] == "已发完":
            messagebox.showinfo("提示", "这批成品已经发完了。", parent=self.win)
            return
        from .shipment_form import ShipmentForm
        if ShipmentForm(self.win, self.cid, from_production=row).result:
            self.win.refresh_all()

    def del_doc(self):
        row = self._pick()
        if not row:
            return
        what = f"缸号 {row['dye_lot']} " if row["dye_lot"] else ""
        if not messagebox.askyesno(
                "确认", f"删除 {row['done_date']} {what}的加工记录"
                        f"（{row['done_rolls']} 卷 / {row['done_meters']:g} 米）？",
                parent=self.win):
            return
        try:
            models.delete_production(row["prod_id"])
        except ValueError as e:
            messagebox.showwarning("不能删除", str(e), parent=self.win)
            return
        self.win.refresh_all()
