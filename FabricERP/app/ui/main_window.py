"""主窗口：客户列表 + 全局功能入口。"""

import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from .. import backup, db, models, updater, version
from .widgets import (FONT_TITLE, AutoRefresh, ReadonlyGrid, fmt_meters,
                      fmt_money, labeled, pin_bottom, setup_style)

COLS = [
    {"key": "customer", "title": "客户名称", "width": 180, "anchor": "w", "stretch": True},
    {"key": "open_batches", "title": "未发完缸数", "width": 90},
    {"key": "greige", "title": "未加工坯布", "width": 105, "anchor": "e"},
    {"key": "fin_meters", "title": "已加工待发", "width": 105, "anchor": "e"},
    {"key": "billed", "title": "累计应收", "width": 115, "anchor": "e"},
    {"key": "paid", "title": "累计已收", "width": 115, "anchor": "e"},
    {"key": "balance", "title": "欠款余额", "width": 115, "anchor": "e"},
    {"key": "phone", "title": "联系电话", "width": 120},
]


class MainWindow(tk.Tk, AutoRefresh):
    def __init__(self):
        super().__init__()
        self.title(f"{version.APP_NAME} {version.full()}")
        self.geometry("1080x640")
        setup_style(self)
        self.tray_icon = None        # 系统托盘图标
        self._children = {}          # customer_id -> CustomerWindow
        self._build()
        self.refresh()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # 会计那台存了东西，这边自己就更新，不用手动切标签页
        self.start_auto(self._auto_refresh)
        # 会计那台（客户端）启动时后台查一下有没有新版本
        if db.is_client():
            threading.Thread(target=self._bg_check_update, daemon=True).start()

    def _build(self):
        top = ttk.Frame(self, padding=(12, 10, 12, 6))
        top.pack(fill="x")
        ttk.Label(top, text="客户一览", font=FONT_TITLE).pack(side="left")
        # 现在用的是本机的账还是别人电脑上的账，得能一眼看见 ——
        # 搞混了会往错的库里录数据，事后很难查。
        self.mode_lbl = ttk.Label(top, foreground="#888")
        self.mode_lbl.pack(side="left", padx=(12, 0))

        right = ttk.Frame(top)
        right.pack(side="right")
        ttk.Button(right, text="基础资料", command=self.open_basedata).pack(side="left", padx=3)
        ttk.Button(right, text="全局库存", command=self.open_stock).pack(side="left", padx=3)
        ttk.Button(right, text="导入数据", command=self.open_import).pack(side="left", padx=3)
        ttk.Button(right, text="导入老账本", command=self.open_legacy).pack(side="left", padx=3)
        self.backup_btn = ttk.Button(right, text="立即备份", command=self.do_backup,
                                     state="disabled" if db.is_client() else "normal")
        self.backup_btn.pack(side="left", padx=3)
        ttk.Button(right, text="设置", command=self.open_settings).pack(side="left", padx=3)

        bar = ttk.Frame(self, padding=(12, 0, 12, 8))
        bar.pack(fill="x")
        ttk.Button(bar, text="＋ 新增客户", style="Accent.TButton",
                   command=self.new_customer).pack(side="left")
        ttk.Button(bar, text="编辑", command=self.edit_customer).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="删除", command=self.del_customer).pack(side="left", padx=(6, 0))

        ttk.Label(bar, text="搜索：").pack(side="left", padx=(20, 2))
        self.kw = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.kw, width=24)
        e.pack(side="left")
        e.bind("<KeyRelease>", lambda _: self.refresh())

        ttk.Label(bar, text="（双击客户进入其单据窗口）",
                  foreground="#666").pack(side="left", padx=16)

        self.grid = ReadonlyGrid(self, COLS, on_double=self.open_customer)
        self.grid.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        self.status = ttk.Label(self, text="", anchor="w", padding=(14, 4))
        self.status.pack(fill="x")

    # ---------- 数据 ----------

    def refresh(self):
        self._show_mode()
        rows = models.list_customers(self.kw.get().strip())

        def vals(r):
            greige = r["stock_meters"] - r["fin_meters"]
            if not r["use_dye_lot"]:
                return (r["customer"], "直接发", "—", "—", fmt_money(r["billed"]),
                        fmt_money(r["paid"]), fmt_money(r["balance"]), r["phone"])
            return (r["customer"], r["open_batches"] or 0,
                    fmt_meters(greige), fmt_meters(r["fin_meters"]),
                    fmt_money(r["billed"]), fmt_money(r["paid"]),
                    fmt_money(r["balance"]), r["phone"])

        self.grid.load(rows, vals, tag_fn=lambda r: "debt" if r["balance"] > 0.005 else None)
        total_debt = sum(r["balance"] for r in rows)
        lot_rows = [r for r in rows if r["use_dye_lot"]]
        total_fin = sum(r["fin_meters"] for r in lot_rows)
        total_greige = sum(r["stock_meters"] - r["fin_meters"] for r in lot_rows)
        self.status.config(
            text=f"共 {len(rows)} 个客户　|　未加工坯布 {fmt_meters(total_greige)} 米"
                 f"　|　已加工待发 {fmt_meters(total_fin)} 米"
                 f"　|　应收合计 {fmt_money(total_debt)} 元")

    def _auto_refresh(self):
        """别人存了东西，自动重读。

        客户窗口自己也在轮询，所以这里只刷客户列表 —— 两边都刷等于同一批
        查询跑两遍，白费。
        """
        self.refresh()
        # 状态栏尾巴上标一下，让人知道刚变过 —— 数字自己跳了却不说一声，
        # 会让人怀疑是不是自己看错了
        from datetime import datetime
        self.status.config(text=self.status.cget("text")
                           + "　|　刚更新 " + datetime.now().strftime("%H:%M:%S"))

    # ---------- 动作 ----------

    def open_customer(self, row):
        from .customer_window import CustomerWindow
        cid = row["customer_id"]
        win = self._children.get(cid)
        if win and win.winfo_exists():
            win.deiconify()
            win.lift()
            win.focus_force()
            return
        self._children[cid] = CustomerWindow(self, cid)

    def new_customer(self):
        if CustomerDialog(self).result:
            self.refresh()

    def edit_customer(self):
        row = self.grid.current()
        if not row:
            messagebox.showinfo("提示", "请先选中一个客户", parent=self)
            return
        if CustomerDialog(self, row["customer_id"]).result:
            self.refresh()

    def del_customer(self):
        row = self.grid.current()
        if not row:
            return
        if not messagebox.askyesno("确认", f"确定删除客户「{row['customer']}」？",
                                   parent=self):
            return
        try:
            models.delete_customer(row["customer_id"])
            self.refresh()
        except ValueError as e:
            messagebox.showwarning("不能删除", str(e), parent=self)

    def open_basedata(self):
        from .basedata_window import BaseDataWindow
        BaseDataWindow(self)

    def open_stock(self):
        from .stock_window import StockWindow
        StockWindow(self)

    def open_import(self):
        from .import_window import ImportWindow
        ImportWindow(self, on_done=self.refresh)

    def open_legacy(self):
        from .legacy_window import LegacyWindow
        LegacyWindow(self, on_done=self.refresh)

    def open_settings(self):
        from .settings_window import SettingsWindow
        SettingsWindow(self)

    def do_backup(self):
        if db.is_client():
            messagebox.showinfo("请在服务器操作",
                                "当前数据在服务器上，请到服务器电脑点击立即备份。",
                                parent=self)
            return
        path = backup.backup_now("manual")
        messagebox.showinfo("备份完成", f"已备份到：\n{path}", parent=self)

    def _show_mode(self):
        from .. import db, server
        cfg = db._client_config()
        if cfg:
            self.mode_lbl.config(text="● 用的是 %s 上的数据" % cfg["host"],
                                 foreground="#1a5fb4")
        elif server.instance().running:
            self.mode_lbl.config(text="● 本机数据，服务开着（别人能连）",
                                 foreground="#1e8449")
        else:
            self.mode_lbl.config(text="", foreground="#888")

    def _on_close(self):
        """点右上角 X：收进右下角托盘，不退出。"""
        self._minimize_to_tray()

    def _minimize_to_tray(self):
        self.withdraw()
        if self.tray_icon is None:
            self._build_tray()
        # 第一次收托盘时提示一下，免得用户以为软件没了
        from .. import db as _db
        if _db.get_setting("tray_hint_shown", "0") != "1":
            _db.set_setting("tray_hint_shown", "1")
            self.after(400, self._tray_hint)

    def _tray_hint(self):
        messagebox.showinfo(
            "已最小化到托盘",
            "软件没有退出，已经收进右下角的托盘里了。\n\n"
            "· 双击托盘图标（或右键点「打开软件」）就能重新打开\n"
            "· 想彻底退出，右键托盘图标点「退出」\n\n"
            "（这个提示只显示这一次）", parent=self)

    def _build_tray(self):
        import pystray
        from .. import tray
        image = tray.load_image()
        menu = pystray.Menu(
            pystray.MenuItem("打开软件", self._on_tray_open, default=True),
            pystray.MenuItem("退出", self._on_tray_exit),
        )
        self.tray_icon = pystray.Icon("FabricERP", image,
                                      version.APP_NAME, menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _on_tray_open(self, icon=None, item=None):
        self.deiconify()
        self.lift()
        self.focus_force()
        self._destroy_tray()

    def _on_tray_exit(self, icon=None, item=None):
        self._real_close()

    def _destroy_tray(self):
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None

    def _real_close(self):
        """真正退出（托盘菜单里的「退出」才走到这里）。"""
        from .. import db, server
        if db.is_client():
            # 数据在服务器那台电脑上，这里没什么要备份的
            self.stop_auto()
            self._shutdown()
            return
        s = server.instance()
        if s.running and not messagebox.askyesno(
                "确认退出",
                "服务正开着。退出以后，别人的电脑和手机就连不上了。\n\n"
                "确定要退出吗？", parent=self):
            return
        self.stop_auto()
        s.stop()
        backup.backup_now("exit")
        self._shutdown()

    def _shutdown(self):
        self._destroy_tray()
        self.destroy()

    # ---------- 自动更新 ----------

    def _bg_check_update(self):
        try:
            has_new, sver, info = updater.check_update()
        except Exception:
            return          # 服务器没开或网络不通，安静跳过
        if has_new:
            self.after(0, lambda: self._prompt_update(sver, info))

    def _prompt_update(self, sver, info):
        if not messagebox.askyesno(
                "发现新版本",
                f"服务器上有新版本 v{sver}（本机 {version.full()}）。\n\n"
                f"是否现在下载并更新？更新时本程序会自动关闭并重启。",
                parent=self):
            return
        self._do_update(sver, info)

    def _do_update(self, sver, info):
        t = updater.server_target()
        if not t:
            return
        base, token = t
        self._upd_dlg = UpdateProgress(self, f"正在下载 v{sver} …")
        self._upd_dlg.show()

        def on_progress(done, total):
            self.after(0, lambda: self._upd_dlg.set(done, total))

        def work():
            try:
                path = updater.download(base, token, info, on_progress)
            except Exception as e:
                self.after(0, lambda: self._upd_dlg.fail(str(e)))
                return
            self.after(0, lambda: self._finish_update(path))

        threading.Thread(target=work, daemon=True).start()

    def _finish_update(self, new_path):
        if getattr(self, "_upd_dlg", None):
            try:
                self._upd_dlg.destroy()
            except Exception:
                pass
        try:
            updater.install_and_restart(new_path)
        except Exception as e:
            messagebox.showerror("更新失败", f"准备更新时出错：\n{e}", parent=self)
            return
        self.stop_auto()
        self.destroy()
        os._exit(0)


class CustomerDialog(tk.Toplevel):
    """新增/编辑客户。"""

    FIELDS = [("name", "客户名称 *", 28), ("code", "客户编号", 28),
              ("contact", "联系人", 28), ("phone", "电话", 28),
              ("address", "地址", 28), ("opening_balance", "期初欠款", 14),
              ("opening_date", "期初日期", 14), ("note", "备注", 28)]

    def __init__(self, master, cid=None):
        super().__init__(master)
        self.cid = cid
        self.result = None
        self.title("编辑客户" if cid else "新增客户")
        self.transient(master)
        self.resizable(False, False)

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        data = models.get_customer(cid) if cid else None

        self.vars = {}
        for i, (key, label, w) in enumerate(self.FIELDS):
            v = tk.StringVar(value=str(data[key] or "") if data else "")
            if key == "opening_balance" and not data:
                v.set("0")
            self.vars[key] = v
            labeled(body, label, ttk.Entry(body, textvariable=v, width=w), i)

        r = len(self.FIELDS)
        self.use_lot = tk.BooleanVar(value=bool(data["use_dye_lot"]) if data else True)
        ttk.Checkbutton(body, text="按缸号管库存（进仓 → 加工 → 发货）",
                        variable=self.use_lot).grid(row=r, column=1, sticky="w",
                                                    padx=(0, 6), pady=2)
        r += 1
        self.track_weight = tk.BooleanVar(
            value=bool(data["track_weight"]) if data else False)
        ttk.Checkbutton(body, text="记录重量（KG）",
                        variable=self.track_weight).grid(row=r, column=1, sticky="w",
                                                         padx=(0, 6), pady=2)
        r += 1

        ttk.Label(body, foreground="#666", wraplength=340, justify="left",
                  text="不勾「按缸号管库存」= 做完直接发、不记库存的客户，"
                       "只有发货和对账，没有进仓和成品两个页面。\n"
                       "期初欠款：启用本系统之前，客户还欠的加工费，会计入对账单。").grid(
            row=r, column=0, columnspan=2, pady=(8, 0))

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
        data = {k: v.get().strip() for k, v in self.vars.items()}
        data["use_dye_lot"] = int(self.use_lot.get())
        data["track_weight"] = int(self.track_weight.get())
        if not data["name"]:
            messagebox.showwarning("提示", "客户名称不能为空", parent=self)
            return
        try:
            data["opening_balance"] = float(data["opening_balance"] or 0)
        except ValueError:
            messagebox.showwarning("提示", "期初欠款必须是数字", parent=self)
            return
        try:
            models.save_customer(data, self.cid)
        except Exception as e:
            messagebox.showerror("保存失败",
                                 "客户名称重复。" if "UNIQUE" in str(e) else str(e),
                                 parent=self)
            return
        self.result = True
        self.destroy()


class UpdateProgress(tk.Toplevel):
    """下载进度小窗。"""

    def __init__(self, master, text):
        super().__init__(master)
        self.parent = master
        self.failed = False
        self.title("更新")
        self.resizable(False, False)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", lambda: None)   # 下载中不许关
        body = ttk.Frame(self, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=text).pack(pady=(0, 8))
        self.var = tk.StringVar(value="准备下载…")
        ttk.Label(body, textvariable=self.var).pack(pady=(0, 8))
        self.bar = ttk.Progressbar(body, mode="determinate", length=320)
        self.bar.pack()

    def show(self):
        self.grab_set()
        self.update_idletasks()

    def set(self, done, total):
        if self.failed:
            return
        if total:
            self.bar["maximum"] = total
            self.bar["value"] = done
            self.var.set(f"{done / 1048576:.1f} / {total / 1048576:.1f} MB")
        else:
            self.var.set(f"{done / 1048576:.1f} MB")

    def fail(self, msg):
        self.failed = True
        self.destroy()
        messagebox.showerror("更新失败", msg, parent=self.parent)
