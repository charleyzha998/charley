"""发货单录入。

三种开单方式：
- 从库存表选中一缸 → 直接开（自动带出面料/颜色/待发数量）
- 从成品库存选中一条 → 直接开
- 无缸号客户（做完直接发的）→ 自己填面料，不挂库存
"""

import tkinter as tk
from tkinter import messagebox, ttk

from .. import models, services
from .widgets import (DateEntry, EditableGrid, ReadonlyGrid, fmt_meters, fmt_money,
                      labeled, pin_bottom)


class ShipmentForm(tk.Toplevel):
    """选缸号自动带出面料/颜色/待发量，选工艺自动带出单价。"""

    def __init__(self, master, customer_id, shipment_id=None,
                 from_batch=None, from_production=None):
        super().__init__(master)
        self.cid = customer_id
        self.sid = shipment_id
        self.result = None
        self.title("编辑发货单" if shipment_id else "新增发货单")
        self.transient(master)

        cust = models.get_customer(customer_id)
        self.use_lot = bool(cust["use_dye_lot"])
        self.track_weight = bool(cust["track_weight"])
        self.geometry("1180x560" if self.use_lot else "1040x520")

        self.processes = {p["name"]: p["id"] for p in models.list_processes()}
        self.fabrics = {f["name"]: f["id"] for f in models.list_fabrics()}
        self.batches = {}
        self._reload_batches()

        head = ttk.Frame(self, padding=(14, 12, 14, 4))
        head.pack(fill="x")
        self.date = DateEntry(head)
        labeled(head, "发货日期", self.date, 0, 0)
        self.doc_no = ttk.Label(head, text="（保存时自动生成）", foreground="#666")
        labeled(head, "单号", self.doc_no, 0, 1)
        self.receiver = tk.StringVar()
        labeled(head, "收货人", ttk.Entry(head, textvariable=self.receiver, width=14), 0, 2)
        self.plate = tk.StringVar()
        labeled(head, "车牌", ttk.Entry(head, textvariable=self.plate, width=12), 0, 3)
        self.note = tk.StringVar()
        labeled(head, "备注", ttk.Entry(head, textvariable=self.note, width=26), 0, 4)

        self.grid = EditableGrid(self, self._build_cols(), on_change=self._on_change,
                                 min_rows=3)
        self.grid.pack(fill="both", expand=True, padx=14, pady=6)

        act = ttk.Frame(self, padding=(14, 0))
        act.pack(fill="x")
        ttk.Button(act, text="＋ 加一行", command=self.grid.add_row).pack(side="left")
        ttk.Button(act, text="删除选中行", command=self.grid.delete_current).pack(
            side="left", padx=6)
        if self.use_lot:
            ttk.Button(act, text="从库存挑缸号…", command=self.pick_batch).pack(side="left")
            ttk.Button(act, text="按待发填满", command=self.fill_left).pack(side="left", padx=6)
        self.total = ttk.Label(act, text="", style="Total.TLabel")
        self.total.pack(side="right")

        tip = ("选缸号自动带出面料/颜色/待发数量，选工艺自动带出价格表单价（可手改）。"
               if self.use_lot else
               "这个客户是做完直接发、不管库存的，直接填面料和数量即可。")
        ttk.Label(self, foreground="#666", padding=(14, 4),
                  text=tip + "　金额 = 米数 × 单价，保存后不随价格表变动。").pack(fill="x")

        btns = ttk.Frame(self, padding=14)
        pin_bottom(btns, self.grid)
        ttk.Button(btns, text="保存", style="Accent.TButton",
                   command=self.save).pack(side="right")
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right", padx=6)

        if shipment_id:
            self._load()
        elif from_production is not None:
            self._prefill_production(from_production)
        elif from_batch is not None:
            self._prefill_batch(from_batch)

        self.bind("<Escape>", lambda _: self.destroy())
        self.grab_set()
        self.wait_window()

    # ---------- 列定义 ----------

    def _build_cols(self):
        cols = []
        if self.use_lot:
            cols += [
                {"key": "dye_lot", "title": "缸号 *", "width": 105, "type": "combo",
                 "values": sorted(self.batches, reverse=True)},
                {"key": "fabric", "title": "面料名称", "width": 145,
                 "type": "readonly", "anchor": "w"},
                {"key": "color", "title": "颜色", "width": 80, "type": "readonly"},
                {"key": "avail", "title": "可发", "width": 130, "type": "readonly"},
            ]
        else:
            cols += [
                {"key": "fabric", "title": "面料名称 *", "width": 160, "type": "combo",
                 "values": sorted(self.fabrics), "anchor": "w"},
                {"key": "color", "title": "颜色", "width": 90},
            ]
        cols += [
            {"key": "process", "title": "工艺", "width": 110, "type": "combo",
             "values": sorted(self.processes)},
            {"key": "rolls", "title": "卷数", "width": 62, "type": "int", "anchor": "e"},
            {"key": "meters", "title": "米数", "width": 92, "type": "float", "anchor": "e"},
        ]
        if self.track_weight:
            cols.append({"key": "weight", "title": "重量KG", "width": 78,
                         "type": "float", "anchor": "e"})
        cols += [
            {"key": "unit_price", "title": "单价", "width": 72, "type": "float", "anchor": "e"},
            {"key": "amount", "title": "金额", "width": 100, "type": "readonly", "anchor": "e"},
            {"key": "note", "title": "备注", "width": 110, "anchor": "w", "stretch": True},
        ]
        return cols

    @property
    def _key_col(self):
        """判断「这一行有没有填东西」看哪一列。"""
        return "dye_lot" if self.use_lot else "fabric"

    # ---------- 数据 ----------

    def _reload_batches(self):
        if self.use_lot:
            self.batches = {b["dye_lot"]: b for b in models.list_batches(self.cid)}

    def _pick_production(self, item_id):
        """这一缸还没发完的成品记录，优先发早做好的那批。"""
        for p in models.list_productions_of_batch(item_id):
            if p["state"] in ("待发货", "部分发货"):
                return p
        return None

    @staticmethod
    def _avail_text(b, prod):
        if prod:
            return f"成品 {prod['left_rolls']}卷/{prod['left_meters']:g}米"
        if b["fin_rolls"] or b["fin_meters"]:
            return f"成品 {b['fin_rolls']}卷/{b['fin_meters']:g}米"
        return f"未加工 {b['greige_rolls']}卷/{b['greige_meters']:g}米"

    def _row_from_batch(self, b):
        prod = self._pick_production(b["item_id"])
        if prod:
            rolls, meters = prod["left_rolls"], round(prod["left_meters"], 2)
            proc = prod["process"]
        else:
            rolls, meters = b["left_rolls"], round(b["left_meters"], 2)
            proc = ""
        return {"dye_lot": b["dye_lot"], "fabric": b["fabric"], "color": b["color"],
                "avail": self._avail_text(b, prod), "process": proc,
                "rolls": max(rolls, 0), "meters": max(meters, 0),
                "_iid": b["item_id"], "_pid": prod["prod_id"] if prod else None}

    def _prefill_batch(self, b):
        b = models.get_batch(b["item_id"])       # 取最新
        row = self._row_from_batch(b)
        self.grid.update_row(0, row)
        self._autofill_price(0, self.grid.get_row(0))
        self._recalc(0)
        self._update_total()

    def _prefill_production(self, p):
        row = {"process": p["process"], "rolls": p["left_rolls"],
               "meters": round(p["left_meters"], 2), "_pid": p["prod_id"],
               "_iid": p["item_id"]}
        if self.use_lot:
            row.update({"dye_lot": p["dye_lot"], "fabric": p["fabric"],
                        "color": p["color"],
                        "avail": f"成品 {p['left_rolls']}卷/{p['left_meters']:g}米"})
        else:
            row.update({"fabric": p["fabric"], "color": p["color"]})
        if self.track_weight and p["weight"]:
            row["weight"] = p["weight"]
        self.grid.update_row(0, row)
        self._autofill_price(0, self.grid.get_row(0))
        self._recalc(0)
        self._update_total()

    def _load(self):
        head, items = models.get_shipment(self.sid)
        self.date.set(head["ship_date"])
        self.doc_no.config(text=head["doc_no"])
        self.receiver.set(head["receiver"] or "")
        self.plate.set(head["plate_no"] or "")
        self.note.set(head["note"] or "")
        rows = []
        for it in items:
            r = {"fabric": it["fabric"], "color": it["color"], "process": it["process"],
                 "rolls": it["rolls"], "meters": it["meters"],
                 "unit_price": it["unit_price"], "amount": fmt_money(it["amount"]),
                 "note": it["note"] or "",
                 "_iid": it["inbound_item_id"], "_pid": it["production_id"]}
            if self.use_lot:
                b = self.batches.get(it["dye_lot"])
                r["dye_lot"] = it["dye_lot"]
                r["avail"] = self._avail_text(b, None) if b else ""
            if self.track_weight:
                r["weight"] = it["weight"] or ""
            rows.append(r)
        self.grid.set_rows(rows)
        self._update_total()

    # ---------- 联动 ----------

    def _on_change(self, r, key, val):
        row = self.grid.get_row(r)
        if key == "dye_lot":
            b = self.batches.get(str(val).strip())
            if b:
                upd = self._row_from_batch(b)
                if row.get("rolls") or row.get("meters"):   # 用户已填数量就别覆盖
                    upd.pop("rolls", None)
                    upd.pop("meters", None)
                if row.get("process"):
                    upd.pop("process", None)
            else:
                upd = {"fabric": "", "color": "", "avail": "缸号不存在",
                       "_iid": None, "_pid": None}
            self.grid.update_row(r, upd)
            row = self.grid.get_row(r)

        if key in ("dye_lot", "process", "fabric"):
            self._autofill_price(r, row)
            row = self.grid.get_row(r)

        if key in ("rolls", "meters", "unit_price", "process", "dye_lot", "fabric"):
            self._recalc(r)
        self._update_total()

    def _autofill_price(self, r, row):
        pid = self.processes.get(str(row.get("process") or "").strip())
        if not pid:
            return
        fabric_id = self._fabric_id_of(row, create=False)
        try:
            on_date = self.date.get()
        except ValueError:
            on_date = None
        price = services.lookup_price(self.cid, fabric_id, pid, on_date)
        if price is not None and not row.get("unit_price"):
            self.grid.update_row(r, {"unit_price": price})

    def _fabric_id_of(self, row, create=True):
        """有缸号时取缸号的面料；无缸号时按名字取（必要时建档）。"""
        if self.use_lot and row.get("_iid"):
            f = models.get_conn().execute(
                "SELECT fabric_id FROM inbound_item WHERE id=?", (row["_iid"],)).fetchone()
            return f["fabric_id"] if f else None
        name = str(row.get("fabric") or "").strip()
        if not name:
            return None
        if create:
            return models.get_or_create_fabric(name)
        return self.fabrics.get(name)

    def _recalc(self, r):
        row = self.grid.get_row(r)
        try:
            amt = services.money(float(row.get("meters") or 0) *
                                 float(row.get("unit_price") or 0))
        except (TypeError, ValueError):
            amt = 0
        self.grid.update_row(r, {"amount": fmt_money(amt)})

    def _update_total(self):
        k = self._key_col
        rows = [r for r in self.grid.get_rows() if str(r.get(k, "")).strip()]
        rolls = sum(int(r.get("rolls") or 0) for r in rows)
        meters = sum(float(r.get("meters") or 0) for r in rows)
        amount = sum(services.money(float(r.get("meters") or 0) *
                                    float(r.get("unit_price") or 0)) for r in rows)
        unit = "缸" if self.use_lot else "项"
        self.total.config(
            text=f"合计 {len(rows)} {unit}　{rolls} 卷　{fmt_meters(meters)} 米　"
                 f"{fmt_money(amount)} 元")

    # ---------- 辅助操作 ----------

    def fill_left(self):
        idx = self.grid.current_index()
        if idx is None:
            return
        self.grid.commit_pending()
        row = self.grid.get_row(idx)
        b = self.batches.get(str(row.get("dye_lot") or "").strip())
        if not b:
            return
        upd = self._row_from_batch(b)
        self.grid.update_row(idx, {"rolls": upd["rolls"], "meters": upd["meters"],
                                   "avail": upd["avail"], "_pid": upd["_pid"]})
        self._recalc(idx)
        self._update_total()

    def pick_batch(self):
        dlg = BatchPicker(self, self.cid)
        if not dlg.result:
            return
        idx = self.grid.current_index()
        for b in dlg.result:
            if idx is not None and not str(
                    self.grid.get_row(idx).get("dye_lot", "")).strip():
                r, idx = idx, None
            else:
                r = self.grid.add_row()
            self.grid.update_row(r, self._row_from_batch(b))
            self._autofill_price(r, self.grid.get_row(r))
            self._recalc(r)
        self._update_total()

    # ---------- 保存 ----------

    def save(self):
        self.grid.commit_pending()
        try:
            ship_date = self.date.get()
        except ValueError as e:
            messagebox.showwarning("日期有误", str(e), parent=self)
            return

        items = []
        for r in self.grid.get_rows():
            key = str(r.get(self._key_col) or "").strip()
            if not key:
                continue
            if self.use_lot and not r.get("_iid"):
                messagebox.showwarning("缸号有误",
                                       f"缸号「{key}」在该客户下不存在，请从下拉中选择。",
                                       parent=self)
                return
            items.append({
                "inbound_item_id": r.get("_iid"),
                "production_id": r.get("_pid"),
                "fabric_id": None if self.use_lot else self._fabric_id_of(r),
                "color": str(r.get("color") or "").strip(),
                "process_id": self.processes.get(str(r.get("process") or "").strip()),
                "rolls": int(r.get("rolls") or 0),
                "meters": float(r.get("meters") or 0),
                "weight": float(r["weight"]) if r.get("weight") else None,
                "unit_price": float(r.get("unit_price") or 0),
                "note": str(r.get("note") or "").strip(),
            })

        if not items:
            messagebox.showwarning("提示", "请至少填写一行明细", parent=self)
            return
        no_price = [i for i in items if i["unit_price"] <= 0]
        if no_price and not messagebox.askyesno(
                "确认", f"有 {len(no_price)} 行单价为 0，金额将记为 0。确定保存？",
                parent=self):
            return

        try:
            self._do_save(ship_date, items, force=False)
        except services.OvershipError as e:
            msg = "\n".join("・" + w for w in e.warnings)
            if not messagebox.askyesno(
                    "超出可发数量",
                    f"以下明细超出剩余：\n\n{msg}\n\n"
                    f"（补数、二次进仓未录入等情况可能出现）\n确定仍然保存？", parent=self):
                return
            try:
                self._do_save(ship_date, items, force=True)
            except Exception as e2:
                messagebox.showerror("保存失败", str(e2), parent=self)
                return
        except Exception as e:
            messagebox.showerror("保存失败", str(e), parent=self)
            return
        self.result = True
        self.destroy()

    def _do_save(self, ship_date, items, force):
        services.save_shipment(self.cid, ship_date, self.receiver.get().strip(),
                               self.plate.get().strip(), self.note.get().strip(),
                               items, self.sid, force=force)


class BatchPicker(tk.Toplevel):
    """从在库缸号中多选。"""

    COLS = [
        {"key": "dye_lot", "title": "缸号", "width": 95},
        {"key": "fabric", "title": "面料名称", "width": 150, "anchor": "w"},
        {"key": "color", "title": "颜色", "width": 80},
        {"key": "in_date", "title": "进仓日期", "width": 92},
        {"key": "greige", "title": "未加工", "width": 110, "anchor": "e"},
        {"key": "fin", "title": "已加工待发", "width": 115, "anchor": "e"},
        {"key": "state", "title": "状态", "width": 78, "stretch": True},
    ]

    def __init__(self, master, customer_id):
        super().__init__(master)
        self.cid = customer_id
        self.result = None
        self.title("挑选缸号（可多选）")
        self.geometry("800x460")
        self.transient(master)

        bar = ttk.Frame(self, padding=(10, 10, 10, 4))
        bar.pack(fill="x")
        ttk.Label(bar, text="搜索：").pack(side="left")
        self.kw = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.kw, width=22)
        e.pack(side="left")
        e.bind("<KeyRelease>", lambda _: self.refresh())
        ttk.Label(bar, text="按住 Ctrl 可多选", foreground="#666").pack(side="left", padx=12)

        self.grid = ReadonlyGrid(self, self.COLS, on_double=lambda r: self.ok())
        self.grid.tree.configure(selectmode="extended")
        self.grid.pack(fill="both", expand=True, padx=10)

        btns = ttk.Frame(self, padding=10)
        pin_bottom(btns, self.grid)
        ttk.Button(btns, text="确定", style="Accent.TButton",
                   command=self.ok).pack(side="right")
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right", padx=6)

        self.refresh()
        e.focus_set()
        self.grab_set()
        self.wait_window()

    def refresh(self):
        rows = models.list_batches(self.cid, self.kw.get().strip(), only_open=True)
        self.grid.load(rows, lambda r: (
            r["dye_lot"], r["fabric"], r["color"], r["in_date"],
            f"{r['greige_rolls']}卷/{fmt_meters(r['greige_meters'])}米",
            f"{r['fin_rolls']}卷/{fmt_meters(r['fin_meters'])}米", r["state"]))

    def ok(self):
        idxs = [self.grid.tree.index(i) for i in self.grid.tree.selection()]
        self.result = [self.grid._data[i] for i in idxs if i < len(self.grid._data)]
        self.destroy()
