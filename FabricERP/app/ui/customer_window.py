"""客户窗口：进仓 / 发货 / 收款 / 对账单 四个 Tab。"""

import tkinter as tk
from tkinter import messagebox, ttk

from .. import models, services
from .widgets import (FONT_TITLE, AutoRefresh, fmt_meters, fmt_money,
                      setup_style)


class CustomerWindow(tk.Toplevel, AutoRefresh):
    def __init__(self, master, customer_id):
        super().__init__(master)
        self.master_win = master
        self.customer_id = customer_id
        self.customer = models.get_customer(customer_id)
        self.title(f"{self.customer['name']} — 单据管理")
        self.geometry("1180x680")
        setup_style(self)

        head = ttk.Frame(self, padding=(14, 10, 14, 4))
        head.pack(fill="x")
        ttk.Label(head, text=self.customer["name"], font=FONT_TITLE).pack(side="left")
        self.summary = ttk.Label(head, text="", style="Total.TLabel")
        self.summary.pack(side="right")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        from .finished_tab import FinishedTab
        from .inbound_tab import InboundTab
        from .payment_tab import PaymentTab
        from .shipment_tab import ShipmentTab
        from .statement_tab import StatementTab

        self.use_lot = bool(self.customer["use_dye_lot"])
        self.tabs = []
        if self.use_lot:
            # 做完直接发的客户（如逸峰）不管库存，进仓/成品两个 Tab 用不上
            self.tab_in = InboundTab(self.nb, self)
            self.tab_fin = FinishedTab(self.nb, self)
            self.nb.add(self.tab_in, text="  进仓库存  ")
            self.nb.add(self.tab_fin, text="  成品库存  ")
            self.tabs += [self.tab_in, self.tab_fin]

        self.tab_out = ShipmentTab(self.nb, self)
        self.tab_pay = PaymentTab(self.nb, self)
        self.tab_stmt = StatementTab(self.nb, self)
        self.nb.add(self.tab_out, text="  发货  ")
        self.nb.add(self.tab_pay, text="  收款  ")
        self.nb.add(self.tab_stmt, text="  对账单  ")
        self.tabs += [self.tab_out, self.tab_pay, self.tab_stmt]
        self.nb.bind("<<NotebookTabChanged>>", lambda _: self.refresh_current())

        self.refresh_all()
        self.protocol("WM_DELETE_WINDOW", self._close)
        # 另一台电脑存了这个客户的单子，这里自己就更新。
        # 主窗口那边也会顺手刷开着的客户窗口，两条路都留着 ——
        # 这个窗口也可能是单独开着的。
        self.start_auto(self.refresh_all)

    def refresh_all(self):
        b = models.get_customer_balance(self.customer_id)
        if self.use_lot:
            txt = (f"未加工坯布 {fmt_meters(b['stock_meters'] - b['fin_meters'])} 米"
                   f"　已加工待发 {fmt_meters(b['fin_meters'])} 米"
                   f"　（{b['open_batches']} 个缸号未发完）"
                   f"　　欠款 {fmt_money(b['balance'])} 元")
        else:
            txt = f"做完直接发，不管库存　　欠款 {fmt_money(b['balance'])} 元"
        self.summary.config(text=txt)
        for t in self.tabs:
            t.refresh()
        if isinstance(self.master_win, tk.Tk):
            self.master_win.refresh()

    def refresh_current(self):
        w = self.nb.nametowidget(self.nb.select())
        w.refresh()

    def _close(self):
        self.stop_auto()
        self.master_win._children.pop(self.customer_id, None)
        self.destroy()
