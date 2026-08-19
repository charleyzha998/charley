"""进仓 Tab：批次库存一览 + 进仓单录入。"""

import tkinter as tk
from tkinter import messagebox, ttk

from .. import models, services
from .widgets import (DateEntry, EditableGrid, ReadonlyGrid, fmt_meters, labeled,
                      parse_num, pin_bottom)

BATCH_COLS = [
    {"key": "in_date", "title": "进仓日期", "width": 92},
    {"key": "dye_lot", "title": "缸号", "width": 92},
    {"key": "fabric", "title": "面料名称", "width": 140, "anchor": "w"},
    {"key": "color", "title": "颜色", "width": 80},
    {"key": "in_rolls", "title": "进仓卷", "width": 60, "anchor": "e"},
    {"key": "in_meters", "title": "进仓米", "width": 82, "anchor": "e"},
    {"key": "greige_rolls", "title": "未加工卷", "width": 72, "anchor": "e"},
    {"key": "greige_meters", "title": "未加工米", "width": 82, "anchor": "e"},
    {"key": "fin_rolls", "title": "待发卷", "width": 62, "anchor": "e"},
    {"key": "fin_meters", "title": "待发米", "width": 82, "anchor": "e"},
    {"key": "out_rolls", "title": "已发卷", "width": 62, "anchor": "e"},
    {"key": "out_meters", "title": "已发米", "width": 82, "anchor": "e"},
    {"key": "state", "title": "状态", "width": 76},
    {"key": "shrink_pct", "title": "缩率%", "width": 64, "anchor": "e"},
    {"key": "note", "title": "备注", "width": 110, "anchor": "w", "stretch": True},
]


class InboundTab(ttk.Frame):
    def __init__(self, master, win):
        super().__init__(master, padding=8)
        self.win = win
        self.cid = win.customer_id

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="＋ 新增进仓单", style="Accent.TButton",
                   command=self.new_doc).pack(side="left")
        ttk.Button(bar, text="登记加工完成", command=self.do_produce).pack(side="left", padx=6)
        ttk.Button(bar, text="发货", style="Accent.TButton",
                   command=self.do_ship).pack(side="left")
        ttk.Button(bar, text="编辑所在单据", command=self.edit_doc).pack(side="left", padx=6)
        ttk.Button(bar, text="查看码单", command=self.view_rolls).pack(side="left")
        ttk.Button(bar, text="标记已结清", command=lambda: self.set_status("closed")).pack(
            side="left", padx=6)
        ttk.Button(bar, text="取消结清", command=lambda: self.set_status("open")).pack(side="left")
        ttk.Button(bar, text="导出 Excel", command=self.export).pack(side="left", padx=(16, 0))

        self.only_open = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="只看未发完", variable=self.only_open,
                        command=self.refresh).pack(side="left", padx=(20, 4))
        ttk.Label(bar, text="搜索：").pack(side="left", padx=(10, 2))
        self.kw = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.kw, width=18)
        e.pack(side="left")
        e.bind("<KeyRelease>", lambda _: self.refresh())

        self.grid = ReadonlyGrid(self, BATCH_COLS, on_double=lambda r: self.do_ship())
        self.grid.pack(fill="both", expand=True)

        self.total = ttk.Label(self, text="", style="Total.TLabel", anchor="e", padding=(0, 6))
        self.total.pack(fill="x")
        ttk.Label(self, foreground="#666", anchor="w",
                  text="选中一行 →「登记加工完成」记录做好了多少，「发货」直接开发货单"
                       "（双击行也可以）。一缸可以分几次加工、开几张发货单。").pack(fill="x")

    def refresh(self):
        rows = models.list_batches(self.cid, self.kw.get().strip(), self.only_open.get())
        self.rows = rows

        def vals(r):
            return (r["in_date"], r["dye_lot"], r["fabric"], r["color"],
                    r["in_rolls"], fmt_meters(r["in_meters"]),
                    r["greige_rolls"], fmt_meters(r["greige_meters"]),
                    r["fin_rolls"], fmt_meters(r["fin_meters"]),
                    r["out_rolls"], fmt_meters(r["out_meters"]), r["state"],
                    "" if r["shrink_pct"] is None else f"{r['shrink_pct']:.2f}",
                    r["note"])

        def tag(r):
            if services.is_shrink_abnormal(r["shrink_pct"]):
                return "warn"
            return "done" if r["state"] in ("已发完", "已结清") else None

        self.grid.load(rows, vals, tag)
        live = [r for r in rows if r["state"] in ("未加工", "待发货", "部分发货")]
        greige = sum(r["greige_meters"] for r in live)
        fin = sum(r["fin_meters"] for r in live)
        self.total.config(
            text=f"共 {len(rows)} 个缸号　|　进仓合计 "
                 f"{fmt_meters(sum(r['in_meters'] for r in rows))} 米"
                 f"　|　未加工坯布 {fmt_meters(greige)} 米"
                 f"　|　已加工待发 {fmt_meters(fin)} 米"
                 f"　|　已发 {fmt_meters(sum(r['out_meters'] for r in rows))} 米")

    # ---------- 加工 / 发货 ----------

    def export(self):
        if not getattr(self, "rows", None):
            messagebox.showinfo("提示", "当前没有可导出的数据", parent=self.win)
            return
        from ..export import excel
        path = excel.export_stock(self.rows, parent=self.win,
                                  customer=self.win.customer["name"])
        if path:
            messagebox.showinfo("导出完成", f"已导出到：\n{path}", parent=self.win)

    def _pick(self):
        row = self.grid.current()
        if not row:
            messagebox.showinfo("提示", "请先选中一个缸号", parent=self.win)
        return row

    def do_produce(self):
        row = self._pick()
        if not row:
            return
        from .production_form import ProductionForm
        if ProductionForm(self.win, self.cid, batch=row).result:
            self.win.refresh_all()

    def do_ship(self):
        row = self._pick()
        if not row:
            return
        from .shipment_form import ShipmentForm
        if ShipmentForm(self.win, self.cid, from_batch=row).result:
            self.win.refresh_all()

    def new_doc(self):
        if InboundForm(self.win, self.cid).result:
            self.win.refresh_all()

    def edit_doc(self):
        row = self.grid.current()
        if not row:
            messagebox.showinfo("提示", "请先选中一行", parent=self.win)
            return
        head = models.get_conn().execute(
            "SELECT inbound_id FROM inbound_item WHERE id=?", (row["item_id"],)).fetchone()
        if InboundForm(self.win, self.cid, head["inbound_id"]).result:
            self.win.refresh_all()

    def view_rolls(self):
        row = self.grid.current()
        if not row:
            return
        RollViewer(self.win, row)

    def set_status(self, status):
        row = self.grid.current()
        if not row:
            return
        if status == "closed" and not messagebox.askyesno(
                "确认", f"把缸号 {row['dye_lot']} 标记为「已结清」？\n"
                        f"用于零头报损、缸号作废等情况，之后不再计入在库。", parent=self.win):
            return
        models.set_batch_status(row["item_id"], status)
        self.win.refresh_all()


class InboundForm(tk.Toplevel):
    """进仓单录入：单头 + 多行明细，明细可展开逐卷码单。"""

    COLS = [
        {"key": "dye_lot", "title": "缸号 *", "width": 110},
        {"key": "fabric", "title": "面料名称", "width": 170, "type": "combo", "anchor": "w"},
        {"key": "color", "title": "颜色", "width": 100, "type": "combo"},
        {"key": "rolls", "title": "卷数", "width": 70, "type": "int", "anchor": "e"},
        {"key": "meters", "title": "米数", "width": 100, "type": "float", "anchor": "e"},
        {"key": "rolls_info", "title": "码单", "width": 70, "type": "readonly"},
        {"key": "note", "title": "备注", "width": 150, "anchor": "w", "stretch": True},
    ]

    def __init__(self, master, customer_id, inbound_id=None):
        super().__init__(master)
        self.cid = customer_id
        self.inbound_id = inbound_id
        self.result = None
        self._rolls = {}          # row_index -> [米数,...]
        self.title("编辑进仓单" if inbound_id else "新增进仓单")
        self.geometry("940x520")
        self.transient(master)

        head = ttk.Frame(self, padding=(14, 12, 14, 4))
        head.pack(fill="x")
        self.date = DateEntry(head)
        labeled(head, "进仓日期", self.date, 0, 0)
        self.doc_no = ttk.Label(head, text="（保存时自动生成）", foreground="#666")
        labeled(head, "单号", self.doc_no, 0, 1)
        self.note = tk.StringVar()
        labeled(head, "备注", ttk.Entry(head, textvariable=self.note, width=40), 0, 2)

        cols = [dict(c) for c in self.COLS]
        cols[1]["values"] = [f["name"] for f in models.list_fabrics()]
        cols[2]["values"] = models.distinct_colors(customer_id)
        self.grid = EditableGrid(self, cols, on_change=self._on_change, min_rows=3)
        self.grid.pack(fill="both", expand=True, padx=14, pady=6)

        act = ttk.Frame(self, padding=(14, 0))
        act.pack(fill="x")
        ttk.Button(act, text="＋ 加一行", command=self.grid.add_row).pack(side="left")
        ttk.Button(act, text="删除选中行", command=self.grid.delete_current).pack(side="left", padx=6)
        ttk.Button(act, text="录入选中行的逐卷码单", command=self.edit_rolls).pack(side="left")
        self.total = ttk.Label(act, text="", style="Total.TLabel")
        self.total.pack(side="right")

        ttk.Label(self, foreground="#666", padding=(14, 4),
                  text="双击格子编辑；Tab 跳下一格；最后一格 Tab 自动加行；选中行按 Delete 删行。"
                       "面料输入新名称会自动建档。").pack(fill="x")

        btns = ttk.Frame(self, padding=14)
        pin_bottom(btns, self.grid)
        ttk.Button(btns, text="保存", style="Accent.TButton",
                   command=self.save).pack(side="right")
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right", padx=6)

        if inbound_id:
            self._load()
        self.bind("<Escape>", lambda _: self.destroy())
        self.grab_set()
        self.wait_window()

    def _load(self):
        head, items = models.get_inbound(self.inbound_id)
        self.date.set(head["in_date"])
        self.doc_no.config(text=head["doc_no"])
        self.note.set(head["note"] or "")
        rows = []
        for i, it in enumerate(items):
            rolls = models.list_rolls(it["id"])
            if rolls:
                self._rolls[i] = [r["meters"] for r in rolls]
            rows.append({"_id": it["id"], "dye_lot": it["dye_lot"], "fabric": it["fabric"],
                         "color": it["color"] or "", "rolls": it["rolls"],
                         "meters": it["meters"], "note": it["note"] or "",
                         "rolls_info": f"{len(rolls)} 卷" if rolls else ""})
        self.grid.set_rows(rows)
        self._update_total()

    def _on_change(self, r, key, val):
        # 录了码单又手改卷数/米数，提示码单已失效
        if key in ("rolls", "meters") and r in self._rolls:
            n, s = len(self._rolls[r]), sum(self._rolls[r])
            row = self.grid.get_row(r)
            if key == "rolls" and val not in ("", n):
                self.grid.update_row(r, {"rolls_info": f"{n} 卷!"})
            if key == "meters" and val not in ("", round(s, 2)):
                self.grid.update_row(r, {"rolls_info": f"{n} 卷!"})
        self._update_total()

    def _update_total(self):
        rows = self.grid.get_rows("dye_lot")
        rolls = sum(int(r["rolls"] or 0) for r in rows)
        meters = sum(float(r["meters"] or 0) for r in rows)
        self.total.config(text=f"合计 {len(rows)} 缸　{rolls} 卷　{fmt_meters(meters)} 米")

    def edit_rolls(self):
        idx = self.grid.current_index()
        if idx is None:
            messagebox.showinfo("提示", "请先选中一行", parent=self)
            return
        self.grid.commit_pending()
        row = self.grid.get_row(idx)
        dlg = RollEditor(self, row.get("dye_lot", ""), self._rolls.get(idx),
                         int(row.get("rolls") or 0))
        if dlg.result is not None:
            self._rolls[idx] = dlg.result
            self.grid.update_row(idx, {
                "rolls": len(dlg.result),
                "meters": round(sum(dlg.result), 2),
                "rolls_info": f"{len(dlg.result)} 卷"})
            self._update_total()

    def save(self):
        self.grid.commit_pending()
        try:
            in_date = self.date.get()
        except ValueError as e:
            messagebox.showwarning("日期有误", str(e), parent=self)
            return

        items = []
        for idx, r in enumerate(self.grid.get_rows()):
            if not str(r.get("dye_lot", "")).strip():
                continue
            fabric_name = str(r.get("fabric") or "").strip()
            item = {
                "id": r.get("_id") or None,
                "dye_lot": str(r["dye_lot"]).strip(),
                "fabric_id": models.get_or_create_fabric(fabric_name) if fabric_name else None,
                "color": str(r.get("color") or "").strip(),
                "rolls": int(r.get("rolls") or 0),
                "meters": float(r.get("meters") or 0),
                "note": str(r.get("note") or "").strip(),
            }
            if idx in self._rolls:
                item["rolls_detail"] = self._rolls[idx]
            items.append(item)

        if not items:
            messagebox.showwarning("提示", "请至少填写一行明细（缸号必填）", parent=self)
            return
        bad = [i["dye_lot"] for i in items if i["rolls"] <= 0 or i["meters"] <= 0]
        if bad and not messagebox.askyesno(
                "确认", f"缸号 {'、'.join(bad)} 的卷数或米数为 0，确定保存？", parent=self):
            return

        try:
            services.save_inbound(self.cid, in_date, self.note.get().strip(),
                                  items, self.inbound_id)
        except ValueError as e:
            messagebox.showwarning("保存失败", str(e), parent=self)
            return
        except Exception as e:
            messagebox.showerror("保存失败", str(e), parent=self)
            return
        self.result = True
        self.destroy()


class RollEditor(tk.Toplevel):
    """逐卷码单录入：一行一卷米数，可直接从磅单粘贴。"""

    def __init__(self, master, dye_lot, values=None, expect_rolls=0):
        super().__init__(master)
        self.result = None
        self.title(f"码单明细 — 缸号 {dye_lot}")
        self.geometry("340x480")
        self.transient(master)

        ttk.Label(self, padding=(12, 10, 12, 4), foreground="#666", wraplength=310,
                  text="一行一卷米数，可从 Excel 整列复制后粘贴。"
                       "保存后自动回填卷数与总米数。").pack(fill="x")

        frame = ttk.Frame(self, padding=(12, 0))
        frame.pack(fill="both", expand=True)
        self.text = tk.Text(frame, width=18, font=("Consolas", 11))
        sb = ttk.Scrollbar(frame, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        if values:
            self.text.insert("1.0", "\n".join(f"{v:g}" for v in values))
        elif expect_rolls:
            self.text.insert("1.0", "\n" * (expect_rolls - 1))

        self.stat = ttk.Label(self, text="", style="Total.TLabel", padding=(12, 6))
        self.stat.pack(fill="x")
        self.text.bind("<KeyRelease>", lambda _: self._stat())
        self._stat()

        btns = ttk.Frame(self, padding=12)
        pin_bottom(btns, frame)
        ttk.Button(btns, text="保存", style="Accent.TButton",
                   command=self.save).pack(side="right")
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right", padx=6)
        ttk.Button(btns, text="清空", command=lambda: self.text.delete("1.0", "end")).pack(
            side="left")

        self.grab_set()
        self.wait_window()

    def _parse(self):
        out = []
        for line in self.text.get("1.0", "end").splitlines():
            line = line.strip().replace(",", "")
            if line:
                out.append(parse_num(line))
        return out

    def _stat(self):
        try:
            v = self._parse()
            self.stat.config(text=f"{len(v)} 卷　合计 {fmt_meters(sum(v))} 米",
                             foreground="black")
        except ValueError as e:
            self.stat.config(text=str(e), foreground="#c00000")

    def save(self):
        try:
            self.result = self._parse()
        except ValueError as e:
            messagebox.showwarning("格式有误", str(e), parent=self)
            return
        self.destroy()


class RollViewer(tk.Toplevel):
    """查看某缸的码单及每卷是否已发。"""

    COLS = [
        {"key": "seq", "title": "卷号", "width": 60},
        {"key": "meters", "title": "米数", "width": 90, "anchor": "e"},
        {"key": "state", "title": "状态", "width": 90},
        {"key": "doc_no", "title": "发货单号", "width": 130},
    ]

    def __init__(self, master, batch):
        super().__init__(master)
        self.title(f"码单 — 缸号 {batch['dye_lot']}（{batch['fabric']} {batch['color']}）")
        self.geometry("420x460")
        self.transient(master)

        rows = models.get_conn().execute(
            """SELECT r.seq, r.meters, sh.doc_no
               FROM roll r
               LEFT JOIN shipment_item si ON si.id = r.shipment_item_id
               LEFT JOIN shipment sh ON sh.id = si.shipment_id
               WHERE r.inbound_item_id=? ORDER BY r.seq""", (batch["item_id"],)).fetchall()

        grid = ReadonlyGrid(self, self.COLS)
        grid.pack(fill="both", expand=True, padx=10, pady=10)
        if rows:
            grid.load(rows, lambda r: (r["seq"], fmt_meters(r["meters"]),
                                       "已发" if r["doc_no"] else "在库", r["doc_no"] or ""),
                      lambda r: "done" if r["doc_no"] else None)
            grid.append_total(("合计", fmt_meters(sum(r["meters"] for r in rows)),
                               f"{len(rows)} 卷", ""))
        else:
            ttk.Label(self, text="该缸号未录入逐卷码单。",
                      foreground="#666").pack(pady=10)

        ttk.Button(self, text="关闭", command=self.destroy).pack(pady=(0, 12))
        self.grab_set()
