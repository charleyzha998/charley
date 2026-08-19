"""基础资料：面料档案 / 工艺档案 / 价格表。"""

import tkinter as tk
from tkinter import messagebox, ttk

from .. import models, services
from .widgets import DateEntry, ReadonlyGrid, labeled, pin_bottom, setup_style


class BaseDataWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("基础资料")
        self.geometry("900x560")
        setup_style(self)
        self.transient(master)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=10)
        self.t_price = PriceTab(nb)
        self.t_fabric = SimpleTab(nb, "fabric")
        self.t_process = SimpleTab(nb, "process")
        nb.add(self.t_price, text="  价格表  ")
        nb.add(self.t_fabric, text="  面料档案  ")
        nb.add(self.t_process, text="  工艺档案  ")


class SimpleTab(ttk.Frame):
    """面料/工艺的简单维护。"""

    CFG = {
        "fabric": ("面料", [{"key": "name", "title": "面料名称", "width": 220, "anchor": "w"},
                          {"key": "spec", "title": "规格（克重/门幅）", "width": 180, "anchor": "w"},
                          {"key": "note", "title": "备注", "width": 240, "anchor": "w",
                           "stretch": True}]),
        "process": ("工艺", [{"key": "name", "title": "工艺名称", "width": 220, "anchor": "w"},
                           {"key": "note", "title": "备注", "width": 320, "anchor": "w",
                            "stretch": True}]),
    }

    def __init__(self, master, kind):
        super().__init__(master, padding=8)
        self.kind = kind
        self.label, cols = self.CFG[kind]

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text=f"＋ 新增{self.label}", style="Accent.TButton",
                   command=self.add).pack(side="left")
        ttk.Button(bar, text="编辑", command=self.edit).pack(side="left", padx=6)
        ttk.Button(bar, text="停用", command=self.remove).pack(side="left")
        ttk.Label(bar, text="（停用后不再出现在下拉中，已有单据不受影响）",
                  foreground="#666").pack(side="left", padx=12)

        self.grid = ReadonlyGrid(self, cols, on_double=lambda r: self.edit())
        self.grid.pack(fill="both", expand=True)
        self.refresh()

    def refresh(self):
        rows = (models.list_fabrics() if self.kind == "fabric" else models.list_processes())
        if self.kind == "fabric":
            self.grid.load(rows, lambda r: (r["name"], r["spec"] or "", r["note"] or ""))
        else:
            self.grid.load(rows, lambda r: (r["name"], r["note"] or ""))

    def add(self):
        self._dialog(None)

    def edit(self):
        row = self.grid.current()
        if row:
            self._dialog(row)

    def _dialog(self, row):
        dlg = tk.Toplevel(self)
        dlg.title(f"{'编辑' if row else '新增'}{self.label}")
        dlg.transient(self)
        dlg.resizable(False, False)
        body = ttk.Frame(dlg, padding=16)
        body.pack()

        name = tk.StringVar(value=row["name"] if row else "")
        labeled(body, f"{self.label}名称 *", ttk.Entry(body, textvariable=name, width=26), 0)
        spec = tk.StringVar(value=(row["spec"] or "") if row and self.kind == "fabric" else "")
        if self.kind == "fabric":
            labeled(body, "规格", ttk.Entry(body, textvariable=spec, width=26), 1)
        note = tk.StringVar(value=(row["note"] or "") if row else "")
        labeled(body, "备注", ttk.Entry(body, textvariable=note, width=26), 2)

        def save():
            if not name.get().strip():
                messagebox.showwarning("提示", "名称不能为空", parent=dlg)
                return
            try:
                if self.kind == "fabric":
                    models.save_fabric(name.get().strip(), spec.get().strip(),
                                       note.get().strip(), row["id"] if row else None)
                else:
                    models.save_process(name.get().strip(), note.get().strip(),
                                        row["id"] if row else None)
            except Exception as e:
                messagebox.showerror("保存失败",
                                     "名称重复。" if "UNIQUE" in str(e) else str(e), parent=dlg)
                return
            dlg.destroy()
            self.refresh()

        # 钉在底边，而且排在 body 前面 —— 内容一多，后 pack 的按钮条会被挤出
        # 窗口，屏幕上看不到「保存」，填完了没法存（会计那台就撞上了这个）。
        btns = ttk.Frame(dlg, padding=(16, 0, 16, 14))
        btns.pack(side="bottom", fill="x", before=body)
        ttk.Button(btns, text="保存", style="Accent.TButton", command=save).pack(side="right")
        ttk.Button(btns, text="取消", command=dlg.destroy).pack(side="right", padx=6)
        dlg.bind("<Return>", lambda _: save())
        dlg.bind("<Escape>", lambda _: dlg.destroy())
        dlg.grab_set()

    def remove(self):
        row = self.grid.current()
        if not row:
            return
        if messagebox.askyesno("确认", f"停用「{row['name']}」？", parent=self):
            models.deactivate(self.kind, row["id"])
            self.refresh()


class PriceTab(ttk.Frame):
    """价格表：客户 + 面料 + 工艺 → 单价。"""

    COLS = [
        {"key": "customer", "title": "客户", "width": 160, "anchor": "w"},
        {"key": "fabric", "title": "面料", "width": 170, "anchor": "w"},
        {"key": "process", "title": "工艺", "width": 110},
        {"key": "unit_price", "title": "单价（元/米）", "width": 110, "anchor": "e"},
        {"key": "effective_date", "title": "生效日期", "width": 100},
        {"key": "note", "title": "备注", "width": 160, "anchor": "w", "stretch": True},
    ]

    def __init__(self, master):
        super().__init__(master, padding=8)

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="＋ 新增价格", style="Accent.TButton",
                   command=self.add).pack(side="left")
        ttk.Button(bar, text="编辑", command=self.edit).pack(side="left", padx=6)
        ttk.Button(bar, text="删除", command=self.remove).pack(side="left")

        ttk.Label(bar, text="客户：").pack(side="left", padx=(20, 2))
        self.cust = ttk.Combobox(bar, width=22, state="readonly")
        self.cust.pack(side="left")
        self.cust.bind("<<ComboboxSelected>>", lambda _: self.refresh())

        self.grid = ReadonlyGrid(self, self.COLS, on_double=lambda r: self.edit())
        self.grid.pack(fill="both", expand=True)

        ttk.Label(self, foreground="#666", anchor="w", padding=(2, 6),
                  text="面料留空 =「通用价」，该客户所有面料的这道工艺都用此价；"
                       "指定面料的价格优先。改价请新增一条更晚的生效日期，"
                       "历史单据金额不受影响。").pack(fill="x")
        self._load_customers()
        self.refresh()

    def _load_customers(self):
        self.customers = models.list_customers()
        names = ["（全部）"] + [c["customer"] for c in self.customers]
        self.cust["values"] = names
        self.cust.current(0)

    def _sel_cid(self):
        i = self.cust.current()
        return self.customers[i - 1]["customer_id"] if i > 0 else None

    def refresh(self):
        rows = models.list_prices(self._sel_cid())
        self.grid.load(rows, lambda r: (r["customer"], r["fabric"], r["process"],
                                        f"{r['unit_price']:g}", r["effective_date"],
                                        r["note"] or ""))

    def add(self):
        PriceDialog(self, None, self._sel_cid())
        self.refresh()

    def edit(self):
        row = self.grid.current()
        if row:
            PriceDialog(self, row)
            self.refresh()

    def remove(self):
        row = self.grid.current()
        if not row:
            return
        if messagebox.askyesno(
                "确认", f"删除价格记录：{row['customer']} / {row['fabric']} / "
                        f"{row['process']} = {row['unit_price']:g}？\n"
                        f"（已开单据的金额不受影响）", parent=self):
            models.delete_price(row["id"])
            self.refresh()


class PriceDialog(tk.Toplevel):
    def __init__(self, master, row=None, default_cid=None):
        super().__init__(master)
        self.row = row
        self.title("编辑价格" if row else "新增价格")
        self.transient(master)
        self.resizable(False, False)

        body = ttk.Frame(self, padding=16)
        body.pack()

        self.customers = models.list_customers()
        self.fabrics = models.list_fabrics()
        self.processes = models.list_processes()

        self.cust = ttk.Combobox(body, width=24, state="readonly",
                                 values=[c["customer"] for c in self.customers])
        labeled(body, "客户 *", self.cust, 0)
        self.fab = ttk.Combobox(body, width=24, state="readonly",
                                values=["（通用 — 所有面料）"] + [f["name"] for f in self.fabrics])
        labeled(body, "面料", self.fab, 1)
        self.proc = ttk.Combobox(body, width=24, state="readonly",
                                 values=[p["name"] for p in self.processes])
        labeled(body, "工艺 *", self.proc, 2)
        self.price = tk.StringVar()
        labeled(body, "单价（元/米）*", ttk.Entry(body, textvariable=self.price, width=12), 3)
        self.date = DateEntry(body)
        labeled(body, "生效日期 *", self.date, 4)
        self.note = tk.StringVar()
        labeled(body, "备注", ttk.Entry(body, textvariable=self.note, width=24), 5)

        self.fab.current(0)
        if row:
            self._fill(row)
        elif default_cid:
            for i, c in enumerate(self.customers):
                if c["customer_id"] == default_cid:
                    self.cust.current(i)

        btns = ttk.Frame(self, padding=(16, 0, 16, 14))
        pin_bottom(btns, body)
        ttk.Button(btns, text="保存", style="Accent.TButton", command=self.save).pack(side="right")
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right", padx=6)
        self.bind("<Return>", lambda _: self.save())
        self.bind("<Escape>", lambda _: self.destroy())
        self.grab_set()
        self.wait_window()

    def _fill(self, row):
        for i, c in enumerate(self.customers):
            if c["customer_id"] == row["customer_id"]:
                self.cust.current(i)
        if row["fabric_id"]:
            for i, f in enumerate(self.fabrics):
                if f["id"] == row["fabric_id"]:
                    self.fab.current(i + 1)
        for i, p in enumerate(self.processes):
            if p["id"] == row["process_id"]:
                self.proc.current(i)
        self.price.set(f"{row['unit_price']:g}")
        self.date.set(row["effective_date"])
        self.note.set(row["note"] or "")

    def save(self):
        if self.cust.current() < 0 or self.proc.current() < 0:
            messagebox.showwarning("提示", "请选择客户和工艺", parent=self)
            return
        try:
            price = float(self.price.get().strip())
            eff = self.date.get()
        except ValueError as e:
            messagebox.showwarning("输入有误", str(e), parent=self)
            return
        if price <= 0:
            messagebox.showwarning("提示", "单价必须大于 0", parent=self)
            return

        fid = None if self.fab.current() <= 0 else self.fabrics[self.fab.current() - 1]["id"]
        try:
            models.save_price(self.customers[self.cust.current()]["customer_id"], fid,
                              self.processes[self.proc.current()]["id"], price, eff,
                              self.note.get().strip(), self.row["id"] if self.row else None)
        except Exception as e:
            messagebox.showerror("保存失败",
                                 "同一客户+面料+工艺+生效日期已存在，请改生效日期。"
                                 if "UNIQUE" in str(e) else str(e), parent=self)
            return
        self.destroy()
