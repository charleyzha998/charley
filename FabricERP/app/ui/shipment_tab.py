"""发货 Tab：送货单列表 + 明细。录入窗口在 shipment_form.py。"""

import tkinter as tk
from tkinter import messagebox, ttk

from .. import models, services
from .widgets import (DateEntry, ReadonlyGrid, fmt_meters, fmt_money,
                      labeled, month_range)

SHIP_COLS = [
    {"key": "ship_date", "title": "发货日期", "width": 95},
    {"key": "doc_no", "title": "送货单号", "width": 130},
    {"key": "n_items", "title": "缸数", "width": 55, "anchor": "e"},
    {"key": "rolls", "title": "卷数", "width": 65, "anchor": "e"},
    {"key": "meters", "title": "米数", "width": 100, "anchor": "e"},
    {"key": "amount", "title": "金额", "width": 110, "anchor": "e"},
    {"key": "receiver", "title": "收货人", "width": 100},
    {"key": "plate_no", "title": "车牌", "width": 90},
    {"key": "note", "title": "备注", "width": 150, "anchor": "w", "stretch": True},
]

DETAIL_COLS = [
    {"key": "dye_lot", "title": "缸号", "width": 100},
    {"key": "fabric", "title": "面料名称", "width": 150, "anchor": "w"},
    {"key": "color", "title": "颜色", "width": 90},
    {"key": "process", "title": "工艺", "width": 110},
    {"key": "rolls", "title": "卷数", "width": 65, "anchor": "e"},
    {"key": "meters", "title": "米数", "width": 95, "anchor": "e"},
    {"key": "unit_price", "title": "单价", "width": 75, "anchor": "e"},
    {"key": "amount", "title": "金额", "width": 105, "anchor": "e"},
    {"key": "note", "title": "备注", "width": 120, "anchor": "w", "stretch": True},
]


class ShipmentTab(ttk.Frame):
    def __init__(self, master, win):
        super().__init__(master, padding=8)
        self.win = win
        self.cid = win.customer_id

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="＋ 新增发货单", style="Accent.TButton",
                   command=self.new_doc).pack(side="left")
        ttk.Button(bar, text="编辑", command=self.edit_doc).pack(side="left", padx=6)
        ttk.Button(bar, text="删除", command=self.del_doc).pack(side="left")
        ttk.Button(bar, text="打印送货单", command=self.print_doc).pack(side="left", padx=(16, 0))
        ttk.Button(bar, text="导出 Excel", command=self.export_doc).pack(side="left", padx=6)

        ttk.Label(bar, text="日期：").pack(side="left", padx=(20, 2))
        f, t = month_range()
        self.d1 = DateEntry(bar, "", width=11)
        self.d1.pack(side="left")
        ttk.Label(bar, text="~").pack(side="left", padx=3)
        self.d2 = DateEntry(bar, "", width=11)
        self.d2.pack(side="left")
        ttk.Button(bar, text="查询", command=self.refresh).pack(side="left", padx=6)
        ttk.Button(bar, text="全部", command=self._clear_dates).pack(side="left")

        panes = ttk.PanedWindow(self, orient="vertical")
        panes.pack(fill="both", expand=True)
        top = ttk.Frame(panes)
        bot = ttk.Frame(panes)
        panes.add(top, weight=3)
        panes.add(bot, weight=2)

        self.grid = ReadonlyGrid(top, SHIP_COLS, on_double=lambda r: self.edit_doc())
        self.grid.pack(fill="both", expand=True)
        self.grid.tree.bind("<<TreeviewSelect>>", lambda _: self._show_detail())

        ttk.Label(bot, text="选中单据的明细：", padding=(2, 4)).pack(anchor="w")
        self.detail = ReadonlyGrid(bot, DETAIL_COLS)
        self.detail.pack(fill="both", expand=True)

        self.total = ttk.Label(self, text="", style="Total.TLabel", anchor="e", padding=(0, 6))
        self.total.pack(fill="x")

    def _clear_dates(self):
        self.d1.set("")
        self.d2.set("")
        self.refresh()

    def _dates(self):
        try:
            return self.d1.get(), self.d2.get()
        except ValueError:
            return None, None

    def refresh(self):
        f, t = self._dates()
        rows = models.list_shipments(self.cid, f, t)

        def vals(r):
            return (r["ship_date"], r["doc_no"], r["n_items"], r["rolls"],
                    fmt_meters(r["meters"]), fmt_money(r["amount"]),
                    r["receiver"] or "", r["plate_no"] or "", r["note"] or "")

        self.grid.load(rows, vals)
        self.total.config(
            text=f"共 {len(rows)} 张单　|　合计 {sum(r['rolls'] for r in rows)} 卷"
                 f"　{fmt_meters(sum(r['meters'] for r in rows))} 米"
                 f"　|　金额 {fmt_money(sum(r['amount'] for r in rows))} 元")
        self.detail.load([], lambda r: ())

    def _show_detail(self):
        row = self.grid.current()
        if not row:
            return
        _, items = models.get_shipment(row["id"])
        self.detail.load(items, lambda r: (
            r["dye_lot"], r["fabric"], r["color"], r["process"], r["rolls"],
            fmt_meters(r["meters"]), f"{r['unit_price']:g}", fmt_money(r["amount"]),
            r["note"] or ""))
        if items:
            self.detail.append_total(
                ("合计", "", "", "", sum(i["rolls"] for i in items),
                 fmt_meters(sum(i["meters"] for i in items)), "",
                 fmt_money(sum(i["amount"] for i in items)), ""))

    def new_doc(self):
        from .shipment_form import ShipmentForm
        if ShipmentForm(self.win, self.cid).result:
            self.win.refresh_all()

    def edit_doc(self):
        from .shipment_form import ShipmentForm
        row = self.grid.current()
        if not row:
            messagebox.showinfo("提示", "请先选中一张单据", parent=self.win)
            return
        if ShipmentForm(self.win, self.cid, row["id"]).result:
            self.win.refresh_all()

    def del_doc(self):
        row = self.grid.current()
        if not row:
            return
        if not messagebox.askyesno(
                "确认", f"删除送货单 {row['doc_no']}？\n删除后该单占用的库存会退回。",
                parent=self.win):
            return
        models.delete_shipment(row["id"])
        self.win.refresh_all()

    def print_doc(self):
        row = self.grid.current()
        if not row:
            messagebox.showinfo("提示", "请先选中一张单据", parent=self.win)
            return
        from ..export import printing
        printing.print_delivery(row["id"])

    def export_doc(self):
        row = self.grid.current()
        if not row:
            messagebox.showinfo("提示", "请先选中一张单据", parent=self.win)
            return
        from ..export import excel
        path = excel.export_delivery(row["id"], parent=self.win)
        if path:
            messagebox.showinfo("导出完成", f"已导出到：\n{path}", parent=self.win)

