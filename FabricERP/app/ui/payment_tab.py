"""收款 Tab：收款流水录入与查询。"""

import tkinter as tk
from tkinter import messagebox, ttk

from .. import models, services
from .widgets import DateEntry, ReadonlyGrid, fmt_money, labeled, pin_bottom

COLS = [
    {"key": "pay_date", "title": "收款日期", "width": 100},
    {"key": "amount", "title": "收款金额", "width": 120, "anchor": "e"},
    {"key": "method", "title": "方式", "width": 80},
    {"key": "ref_no", "title": "凭证/流水号", "width": 160, "anchor": "w"},
    {"key": "note", "title": "备注", "width": 240, "anchor": "w", "stretch": True},
]


class PaymentTab(ttk.Frame):
    def __init__(self, master, win):
        super().__init__(master, padding=8)
        self.win = win
        self.cid = win.customer_id

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="＋ 登记收款", style="Accent.TButton",
                   command=self.new_pay).pack(side="left")
        ttk.Button(bar, text="编辑", command=self.edit_pay).pack(side="left", padx=6)
        ttk.Button(bar, text="删除", command=self.del_pay).pack(side="left")

        ttk.Label(bar, text="日期：").pack(side="left", padx=(20, 2))
        self.d1 = DateEntry(bar, "", width=11)
        self.d1.pack(side="left")
        ttk.Label(bar, text="~").pack(side="left", padx=3)
        self.d2 = DateEntry(bar, "", width=11)
        self.d2.pack(side="left")
        ttk.Button(bar, text="查询", command=self.refresh).pack(side="left", padx=6)
        ttk.Button(bar, text="全部", command=self._clear).pack(side="left")

        self.grid = ReadonlyGrid(self, COLS, on_double=lambda r: self.edit_pay())
        self.grid.pack(fill="both", expand=True)

        self.total = ttk.Label(self, text="", style="Total.TLabel", anchor="e", padding=(0, 6))
        self.total.pack(fill="x")

    def _clear(self):
        self.d1.set("")
        self.d2.set("")
        self.refresh()

    def refresh(self):
        try:
            f, t = self.d1.get(), self.d2.get()
        except ValueError:
            f = t = None
        rows = models.list_payments(self.cid, f, t)
        self.grid.load(rows, lambda r: (r["pay_date"], fmt_money(r["amount"]),
                                        r["method"], r["ref_no"] or "", r["note"] or ""))
        bal = models.get_customer_balance(self.cid)
        self.total.config(
            text=f"本区间收款 {len(rows)} 笔　合计 {fmt_money(sum(r['amount'] for r in rows))} 元"
                 f"　　|　　当前欠款余额 {fmt_money(bal['balance'])} 元")

    def new_pay(self):
        if PaymentDialog(self.win, self.cid).result:
            self.win.refresh_all()

    def edit_pay(self):
        row = self.grid.current()
        if not row:
            messagebox.showinfo("提示", "请先选中一笔收款", parent=self.win)
            return
        if PaymentDialog(self.win, self.cid, row).result:
            self.win.refresh_all()

    def del_pay(self):
        row = self.grid.current()
        if not row:
            return
        if messagebox.askyesno("确认", f"删除 {row['pay_date']} 的 "
                                       f"{fmt_money(row['amount'])} 元收款记录？",
                               parent=self.win):
            models.delete_payment(row["id"])
            self.win.refresh_all()


class PaymentDialog(tk.Toplevel):
    def __init__(self, master, customer_id, row=None):
        super().__init__(master)
        self.cid = customer_id
        self.row = row
        self.result = None
        self.title("编辑收款" if row else "登记收款")
        self.transient(master)
        self.resizable(False, False)

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)

        self.date = DateEntry(body, row["pay_date"] if row else None)
        labeled(body, "收款日期", self.date, 0)

        self.amount = tk.StringVar(value=f"{row['amount']:g}" if row else "")
        labeled(body, "收款金额", ttk.Entry(body, textvariable=self.amount, width=16), 1)

        self.method = tk.StringVar(value=row["method"] if row else "转账")
        labeled(body, "收款方式", ttk.Combobox(body, textvariable=self.method, width=14,
                                           values=services.METHODS, state="readonly"), 2)

        self.ref = tk.StringVar(value=(row["ref_no"] or "") if row else "")
        labeled(body, "凭证/流水号", ttk.Entry(body, textvariable=self.ref, width=26), 3)

        self.note = tk.StringVar(value=(row["note"] or "") if row else "")
        labeled(body, "备注", ttk.Entry(body, textvariable=self.note, width=26), 4)

        bal = models.get_customer_balance(customer_id)
        ttk.Label(body, text=f"该客户当前欠款：{fmt_money(bal['balance'])} 元",
                  foreground="#c00000").grid(row=5, column=0, columnspan=2, pady=(8, 0))

        btns = ttk.Frame(self, padding=(16, 0, 16, 14))
        pin_bottom(btns, body)
        ttk.Button(btns, text="保存", style="Accent.TButton",
                   command=self.save).pack(side="right")
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right", padx=6)

        self.bind("<Return>", lambda _: self.save())
        self.bind("<Escape>", lambda _: self.destroy())
        self.grab_set()
        self.wait_window()

    def save(self):
        try:
            pay_date = self.date.get()
            amount = float(str(self.amount.get()).replace(",", "").strip() or 0)
        except ValueError as e:
            messagebox.showwarning("输入有误", str(e), parent=self)
            return
        if amount == 0:
            messagebox.showwarning("提示", "收款金额不能为 0（退款请填负数）", parent=self)
            return
        models.save_payment(self.cid, pay_date, amount, self.method.get(),
                            self.ref.get().strip(), self.note.get().strip(),
                            self.row["id"] if self.row else None)
        self.result = True
        self.destroy()
