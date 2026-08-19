"""加工完成录入：某一缸今天做好了多少（还没发货）。

这一步把货从「未加工的坯布」挪到「已加工待发的成品」。
对账单不受影响 —— 发货了才算钱。
"""

import tkinter as tk
from tkinter import messagebox, ttk

from .. import models, services
from .widgets import (AutocompleteCombobox, DateEntry, fmt_meters, labeled,
                      parse_int, parse_num, pin_bottom)


class ProductionForm(tk.Toplevel):
    def __init__(self, master, customer_id, batch=None, prod_id=None):
        """batch: v_batch_stock 的一行（从库存表点进来）；prod_id: 编辑已有记录。"""
        super().__init__(master)
        self.cid = customer_id
        self.prod_id = prod_id
        self.batch = batch
        self.result = None
        self.title("修改加工记录" if prod_id else "登记加工完成")
        self.resizable(False, False)
        self.transient(master)

        cust = models.get_customer(customer_id)
        self.use_lot = bool(cust["use_dye_lot"])
        self.track_weight = bool(cust["track_weight"])
        self.processes = {p["name"]: p["id"] for p in models.list_processes()}
        self.fabrics = {f["name"]: f["id"] for f in models.list_fabrics()}
        self.batches = {b["dye_lot"]: b for b in models.list_batches(customer_id)}

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        r = 0

        self.date = DateEntry(body)
        labeled(body, "加工完成日期 *", self.date, r); r += 1

        if self.use_lot:
            self.lot = tk.StringVar(value=batch["dye_lot"] if batch else "")
            box = AutocompleteCombobox(body, sorted(self.batches, reverse=True),
                                       textvariable=self.lot, width=20)
            box.bind("<<ComboboxSelected>>", lambda _: self._on_lot())
            box.bind("<FocusOut>", lambda _: self._on_lot())
            labeled(body, "缸号 *", box, r); r += 1

            self.info = ttk.Label(body, text="", foreground="#0a5", wraplength=300,
                                  justify="left")
            self.info.grid(row=r, column=1, sticky="w", padx=(0, 6)); r += 1
        else:
            self.lot = None

        self.fabric = tk.StringVar()
        labeled(body, "面料名称", AutocompleteCombobox(
            body, sorted(self.fabrics), textvariable=self.fabric, width=20), r); r += 1

        self.color = tk.StringVar()
        labeled(body, "颜色", AutocompleteCombobox(
            body, models.distinct_colors(customer_id),
            textvariable=self.color, width=20), r); r += 1

        self.process = tk.StringVar()
        labeled(body, "工艺", AutocompleteCombobox(
            body, sorted(self.processes), textvariable=self.process, width=20), r); r += 1

        self.rolls = tk.StringVar()
        labeled(body, "成品卷数", ttk.Entry(body, textvariable=self.rolls, width=12), r); r += 1

        self.meters = tk.StringVar()
        labeled(body, "成品米数 *", ttk.Entry(body, textvariable=self.meters, width=12), r); r += 1

        if self.track_weight:
            self.weight = tk.StringVar()
            labeled(body, "重量 KG", ttk.Entry(body, textvariable=self.weight, width=12), r)
            r += 1
        else:
            self.weight = None

        self.note = tk.StringVar()
        labeled(body, "备注", ttk.Entry(body, textvariable=self.note, width=26), r); r += 1

        ttk.Label(body, foreground="#666", wraplength=340, justify="left",
                  text="这里只记「做好了多少」，不算钱。发货以后才进对账单。\n"
                       "一缸可以分几次做，每做一批登记一次。").grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(8, 0))

        btns = ttk.Frame(self, padding=(16, 0, 16, 14))
        pin_bottom(btns, body)
        ttk.Button(btns, text="保存", style="Accent.TButton",
                   command=self.save).pack(side="right")
        ttk.Button(btns, text="保存并开发货单", command=self.save_and_ship).pack(
            side="right", padx=6)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right")

        if prod_id:
            self._load()
        elif batch:
            self._on_lot()

        self.bind("<Escape>", lambda _: self.destroy())
        self.grab_set()
        self.wait_window()

    # ---------- 联动 ----------

    def _on_lot(self):
        """选了缸号：带出面料/颜色，并显示还剩多少坯布没做。"""
        if not self.lot:
            return
        b = self.batches.get(self.lot.get().strip())
        if not b:
            self.info.config(text="缸号不存在", foreground="#c00")
            return
        self.info.config(
            text=f"未加工坯布 {b['greige_rolls']} 卷 / {fmt_meters(b['greige_meters'])} 米"
                 f"　已加工待发 {b['fin_rolls']} 卷 / {fmt_meters(b['fin_meters'])} 米",
            foreground="#0a5")
        if not self.fabric.get():
            self.fabric.set(b["fabric"])
        if not self.color.get():
            self.color.set(b["color"])
        if not self.rolls.get() and b["greige_rolls"] > 0:
            self.rolls.set(str(b["greige_rolls"]))
        if not self.meters.get() and b["greige_meters"] > 0:
            self.meters.set(f"{b['greige_meters']:g}")

    def _load(self):
        p = models.get_finished(self.prod_id)
        self.date.set(p["done_date"])
        if self.lot:
            self.lot.set(p["dye_lot"])
            self._on_lot()
        self.fabric.set(p["fabric"])
        self.color.set(p["color"])
        self.process.set(p["process"])
        self.rolls.set(str(p["done_rolls"]))
        self.meters.set(f"{p['done_meters']:g}")
        if self.weight is not None and p["weight"] is not None:
            self.weight.set(f"{p['weight']:g}")
        self.note.set(p["note"])

    # ---------- 保存 ----------

    def _collect(self):
        try:
            done_date = self.date.get()
        except ValueError as e:
            messagebox.showwarning("日期有误", str(e), parent=self)
            return None

        iid = None
        if self.lot:
            lot = self.lot.get().strip()
            if not lot:
                messagebox.showwarning("提示", "请选择缸号", parent=self)
                return None
            b = self.batches.get(lot)
            if not b:
                messagebox.showwarning("提示", f"缸号「{lot}」在该客户下不存在。",
                                       parent=self)
                return None
            iid = b["item_id"]

        meters = parse_num(self.meters.get())
        rolls = parse_int(self.rolls.get())
        if meters <= 0 and rolls <= 0:
            messagebox.showwarning("提示", "成品卷数和米数不能都是 0", parent=self)
            return None

        fab = self.fabric.get().strip()
        return {
            "customer_id": self.cid,
            "inbound_item_id": iid,
            "done_date": done_date,
            "process_id": self.processes.get(self.process.get().strip()),
            "fabric_id": models.get_or_create_fabric(fab) if fab else None,
            "color": self.color.get().strip(),
            "rolls": rolls,
            "meters": meters,
            "weight": parse_num(self.weight.get()) if self.weight else None,
            "note": self.note.get().strip(),
        }

    def _save(self):
        data = self._collect()
        if data is None:
            return None
        try:
            pid, warns = services.save_production(data, self.prod_id)
        except services.OverproduceError as e:
            msg = "\n".join("・" + w for w in e.warnings)
            if not messagebox.askyesno(
                    "坯布不够", f"{msg}\n\n（进仓少录、二次补料等情况可能出现）\n"
                                f"确定仍然保存？", parent=self):
                return None
            pid, warns = services.save_production(data, self.prod_id, force=True)
        except Exception as e:
            messagebox.showerror("保存失败", str(e), parent=self)
            return None
        self.result = pid
        return pid

    def save(self):
        if self._save():
            self.destroy()

    def save_and_ship(self):
        """做好了就直接发 —— 保存后立刻弹发货单，成品已带好。"""
        pid = self._save()
        if not pid:
            return
        self.destroy()
        from .shipment_form import ShipmentForm
        ShipmentForm(self.master, self.cid, from_production=models.get_finished(pid))
