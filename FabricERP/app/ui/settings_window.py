"""设置窗口：公司抬头、计价基数、缩率阈值、备份管理。"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import backup, db, db_merge, updater, version
from ..db import get_setting, set_setting
from .merge_window import MergePreviewWindow
from .widgets import ReadonlyGrid, SKINS, labeled, setup_style


class SettingsWindow(tk.Toplevel):
    FIELDS = [
        ("company_name", "工厂名称", "打印在送货单/对账单抬头"),
        ("company_address", "地址", ""),
        ("company_phone", "电话", ""),
        ("company_bank", "开户行及账号", "打印在对账单底部"),
    ]

    def __init__(self, master):
        super().__init__(master)
        self.title(f"设置 — {version.full()}")
        self.geometry("580x640")
        self.minsize(560, 480)        # 再小就该出滚动条了，别把按钮挤没
        setup_style(self)
        self.transient(master)

        # 按钮条先摆，而且钉在底边。
        # 原先是先摆 notebook（expand=True）再摆按钮条 —— pack 按顺序分地方，
        # 「多人共用/手机」那一页内容高，notebook 把高度全占了，按钮条就被挤到
        # 窗口外面，会计那台的屏幕上根本看不到「保存」，设置自然存不住。
        btns = ttk.Frame(self, padding=(10, 8, 10, 12))
        btns.pack(side="bottom", fill="x")
        ttk.Button(btns, text="保存", style="Accent.TButton",
                   command=self.save).pack(side="right")
        ttk.Button(btns, text="关闭", command=self.destroy).pack(side="right", padx=6)

        nb = ttk.Notebook(self)
        nb.pack(side="top", fill="both", expand=True, padx=10, pady=(10, 0))
        nb.add(self._tab_company(nb), text="  公司信息  ")
        nb.add(self._tab_rules(nb), text="  业务规则  ")
        nb.add(self._tab_backup(nb), text="  备份  ")
        nb.add(self._tab_net(nb), text="  多人共用/手机  ")
        self.grab_set()

    def _tab_company(self, nb):
        f = ttk.Frame(nb, padding=16)
        self.vars = {}
        for i, (key, label, hint) in enumerate(self.FIELDS):
            v = tk.StringVar(value=get_setting(key))
            self.vars[key] = v
            labeled(f, label, ttk.Entry(f, textvariable=v, width=36), i)
            if hint:
                ttk.Label(f, text=hint, foreground="#888").grid(
                    row=i, column=2, sticky="w", padx=6)
        ttk.Label(f, foreground="#666", wraplength=460, justify="left",
                  text="这些信息只用于打印和导出的表头/表尾，不填也能正常使用软件。").grid(
            row=len(self.FIELDS), column=0, columnspan=3, pady=(14, 0), sticky="w")
        return f

    def _tab_rules(self, nb):
        f = ttk.Frame(nb, padding=16)

        ttk.Label(f, text="加工费计价基数", font=("Microsoft YaHei UI", 10, "bold")).pack(
            anchor="w")
        self.basis = tk.StringVar(value=get_setting("billing_basis", "out"))
        ttk.Radiobutton(f, text="按发货米数计费（成品米 × 单价）—— 常用",
                        variable=self.basis, value="out").pack(anchor="w", pady=(6, 0))
        ttk.Radiobutton(f, text="按进仓米数计费（坯布米 × 单价，按发货卷数折算）",
                        variable=self.basis, value="in").pack(anchor="w")
        ttk.Label(f, foreground="#666", wraplength=470, justify="left",
                  text="切换只影响之后新开的单据；已保存单据的金额是快照，不会变动。").pack(
            anchor="w", pady=(4, 18))

        ttk.Label(f, text="缩率异常提醒阈值", font=("Microsoft YaHei UI", 10, "bold")).pack(
            anchor="w")
        row = ttk.Frame(f)
        row.pack(anchor="w", pady=6)
        self.shrink = tk.StringVar(value=get_setting("shrink_warn_pct", "8"))
        ttk.Label(row, text="缩率超过").pack(side="left")
        ttk.Entry(row, textvariable=self.shrink, width=6).pack(side="left", padx=4)
        ttk.Label(row, text="% 时，该批次标黄提醒").pack(side="left")
        ttk.Label(f, foreground="#666", wraplength=470, justify="left",
                  text="缩率 =（进仓米 − 发货米）÷ 进仓米，发完时才计算。\n"
                       "缩率为负数（发货比进仓还多）一律标黄，通常意味着录错了数字。").pack(
            anchor="w", pady=(0, 18))

        ttk.Label(f, text="备份保留份数", font=("Microsoft YaHei UI", 10, "bold")).pack(
            anchor="w")
        row2 = ttk.Frame(f)
        row2.pack(anchor="w", pady=6)
        self.keep = tk.StringVar(value=get_setting("backup_keep", "30"))
        ttk.Label(row2, text="保留最近").pack(side="left")
        ttk.Entry(row2, textvariable=self.keep, width=6).pack(side="left", padx=4)
        ttk.Label(row2, text="份，多余的自动删除").pack(side="left")

        ttk.Label(f, text="界面皮肤", font=("Microsoft YaHei UI", 10, "bold")).pack(
            anchor="w", pady=(18, 0))
        row3 = ttk.Frame(f)
        row3.pack(anchor="w", pady=6)
        cur = SKINS.get(get_setting("skin", "default"), SKINS["default"])[0]
        self.skin_name = tk.StringVar(value=cur)
        ttk.Combobox(row3, textvariable=self.skin_name, state="readonly", width=14,
                     values=[v[0] for v in SKINS.values()]).pack(side="left")
        ttk.Label(f, foreground="#666", wraplength=470, justify="left",
                  text="皮肤改的是表格标题、选中行和主按钮的颜色；保存后重启软件生效。").pack(
            anchor="w", pady=(4, 0))
        return f

    def _tab_backup(self, nb):
        f = ttk.Frame(nb, padding=12)
        cfg = db._client_config()
        location = ("当前使用服务器 %s 上的数据。备份和数据库合并请在服务器电脑操作。"
                    % cfg["host"] if cfg else "数据库位置：\n%s" % db.DB_PATH)
        ttk.Label(f, text=location, foreground="#666", wraplength=500,
                  justify="left").pack(anchor="w", pady=(0, 8))

        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(0, 6))
        state = "disabled" if cfg else "normal"
        self.backup_btn = ttk.Button(bar, text="立即备份", style="Accent.TButton",
                                     command=self._do_backup, state=state)
        self.backup_btn.pack(side="left")
        self.restore_btn = ttk.Button(bar, text="从选中备份恢复",
                                      command=self._do_restore, state=state)
        self.restore_btn.pack(side="left", padx=6)
        self.open_backup_btn = ttk.Button(bar, text="打开备份文件夹",
                                          command=self._open_dir, state=state)
        self.open_backup_btn.pack(side="left")

        merge_bar = ttk.Frame(f)
        merge_bar.pack(fill="x", pady=(0, 8))
        self.merge_btn = ttk.Button(
            merge_bar, text="合并另一台电脑的数据…", command=self._merge_database,
            state=state)
        self.merge_btn.pack(side="left")
        ttk.Label(merge_bar, text="先预览，只新增，不覆盖服务器",
                  foreground="#777").pack(side="left", padx=8)

        self.blist = ReadonlyGrid(f, [
            {"key": "name", "title": "备份文件", "width": 300, "anchor": "w", "stretch": True},
            {"key": "size", "title": "大小", "width": 90, "anchor": "e"}])
        self.blist.pack(fill="both", expand=True)
        self._refresh_backups()

        ttk.Label(f, foreground="#666", wraplength=480, justify="left", padding=(0, 8),
                  text="程序每次启动和退出都会自动备份。恢复会先把当前数据备份一份，"
                       "恢复完成后需要重启程序。").pack(anchor="w")
        return f

    # ---------------- 多人共用 / 手机 ----------------

    def _tab_net(self, nb):
        """两种角色，选一个：

        · 这台电脑管数据（服务器）—— 数据库在本机，别人连过来
        · 这台电脑连别人的（客户端）—— 数据库在那台电脑上

        分开两块摆，是因为选错了后果不一样：会计那台要是当成服务器开着，
        就变成两套账各记一半，看着都正常，等对账时才发现对不上。
        """
        f = ttk.Frame(nb, padding=14)
        self.role = tk.StringVar(value="client" if db.is_client() else "server")

        # 当前到底在用谁的库，写在最上面。两个圆点看着差不多，
        # 但选错了就是各记一套账，得让人一眼看见现在是哪种。
        cfg0 = db._client_config()
        ttk.Label(f, justify="left", wraplength=490,
                  foreground="#1e8449" if cfg0 else "#b9770e",
                  text=("现在：用的是 %s:%s 上的数据（本机不存）"
                        % (cfg0["host"], cfg0["port"])) if cfg0 else
                       "现在：用本机的数据"
                  ).pack(anchor="w", pady=(0, 8))

        ttk.Radiobutton(f, text="这台电脑管数据（数据库在本机，别人连过来看和改）",
                        variable=self.role, value="server",
                        command=self._role_changed).pack(anchor="w")

        srv = ttk.Frame(f, padding=(22, 4, 0, 10))
        srv.pack(fill="x")
        self.srv_on = tk.BooleanVar(value=get_setting("server_enabled", "0") == "1")
        ttk.Checkbutton(srv, text="开机就开着服务", variable=self.srv_on).pack(anchor="w")
        self.autostart_on = tk.BooleanVar(value=get_setting("autostart_enabled", "0") == "1")
        ttk.Checkbutton(srv, text="开机自动打开本软件（电脑一开机，会计就能连）",
                        variable=self.autostart_on).pack(anchor="w")
        row = ttk.Frame(srv)
        row.pack(anchor="w", pady=4)
        ttk.Label(row, text="端口").pack(side="left")
        self.srv_port = tk.StringVar(value=get_setting("server_port", "8756"))
        ttk.Entry(row, textvariable=self.srv_port, width=8).pack(side="left", padx=4)
        ttk.Label(row, text="口令").pack(side="left", padx=(10, 0))
        # 口令还没生成过就现在生成 —— 这一页是给人抄口令用的，不能显示空白
        self.srv_token = tk.StringVar(value=self._server_token())
        ttk.Entry(row, textvariable=self.srv_token, width=22,
                  state="readonly").pack(side="left", padx=4)
        ttk.Button(row, text="换一个", command=self._new_token).pack(side="left")

        bar = ttk.Frame(srv)
        bar.pack(anchor="w", pady=4)
        self.srv_btn = ttk.Button(bar, text="现在就开", command=self._toggle_server)
        self.srv_btn.pack(side="left")
        ttk.Button(bar, text="复制手机网址",
                   command=self._copy_mobile).pack(side="left", padx=6)
        self.srv_state = ttk.Label(srv, foreground="#666", justify="left",
                                   wraplength=470)
        self.srv_state.pack(anchor="w", pady=(2, 0))

        ttk.Separator(f).pack(fill="x", pady=8)

        ttk.Radiobutton(f, text="这台电脑连别人的（数据库在那台电脑上，本机不存数据）",
                        variable=self.role, value="client",
                        command=self._role_changed).pack(anchor="w")
        cli = ttk.Frame(f, padding=(22, 6, 0, 0))
        cli.pack(fill="x")
        cfg = db._client_config() or {}
        self.cli_host = tk.StringVar(value=cfg.get("host", ""))
        self.cli_port = tk.StringVar(value=str(cfg.get("port", 8756)))
        self.cli_token = tk.StringVar(value=cfg.get("token", ""))
        for i, (lab, var, w) in enumerate((
                ("那台电脑的地址", self.cli_host, 22),
                ("端口", self.cli_port, 8),
                ("口令", self.cli_token, 22))):
            labeled(cli, lab, ttk.Entry(cli, textvariable=var, width=w), i)
        bts = ttk.Frame(cli)
        bts.grid(row=3, column=1, sticky="w", pady=6)
        ttk.Button(bts, text="测试连接", command=self._test_client).pack(side="left")
        ttk.Button(bts, text="检查更新", command=self._check_update).pack(
            side="left", padx=6)
        self.cli_state = ttk.Label(cli, foreground="#666", justify="left",
                                   wraplength=440)
        self.cli_state.grid(row=4, column=0, columnspan=3, sticky="w")

        ttk.Label(f, foreground="#888", wraplength=480, justify="left",
                  text="地址、端口、口令在那台电脑的这个页面上抄。\n"
                       "改完角色要重启软件才生效。\n"
                       "手机在外面看要先装 Tailscale，两边登同一个账号，"
                       "然后用 Tailscale 给的地址。\n"
                       "别在路由器上把这个端口转发到公网上 —— 口令拦不住扫端口的。"
                  ).pack(anchor="w", pady=(10, 0))

        self._role_changed()
        ttk.Label(f, text=f"当前版本：{version.full()}",
                   foreground="#888").pack(anchor="w", pady=(12, 0))

        self._refresh_server_state()
        return f

    def _role_changed(self):
        pass        # 两块都留着能看能改，保存时按选中的角色写

    def _server_token(self):
        """本机的服务口令，没有就生成一个。客户端模式下不生成 —— 那台电脑
        的口令在服务器那边，这里显示自己的只会让人抄错。"""
        if db.is_client():
            return ""
        from .. import server
        return server.token()

    def _new_token(self):
        import secrets
        self.srv_token.set(secrets.token_urlsafe(12))
        set_setting("server_token", self.srv_token.get())
        self.srv_state.config(
            text="口令换好了。别的电脑和手机要用新口令重新连一次。")

    def _refresh_server_state(self):
        from .. import server
        s = server.instance()
        if s.running:
            u = s.urls
            self.srv_btn.config(text="停掉服务")
            self.srv_state.config(
                text="服务开着。\n别的电脑填地址：%s\n手机浏览器打开：%s"
                     % (u["client"], u["mobile"]))
        else:
            self.srv_btn.config(text="现在就开")
            self.srv_state.config(text=s.error or "服务没开。")

    def _toggle_server(self):
        from .. import server
        if db.is_client():
            messagebox.showinfo(
                "提示", "这台电脑现在是连别人的（客户端），数据库不在本机，"
                        "不用开服务。要改的话先在上面选「这台电脑管数据」，"
                        "保存后重启软件。", parent=self)
            return
        s = server.instance()
        if s.running:
            s.stop()
        else:
            try:
                s.port = int(self.srv_port.get())
            except ValueError:
                pass
            if not s.start():
                messagebox.showerror("开不起来", s.error, parent=self)
        self.srv_token.set(server.token())
        self._refresh_server_state()

    def _copy_mobile(self):
        from .. import server
        s = server.instance()
        if not s.running:
            messagebox.showinfo("提示", "先把服务开起来。", parent=self)
            return
        self.clipboard_clear()
        self.clipboard_append(s.urls["mobile"])
        messagebox.showinfo("已复制", "网址已复制，发到手机上打开即可。\n\n"
                                     + s.urls["mobile"], parent=self)

    def _test_client(self):
        from .. import remote_db
        try:
            port = int(self.cli_port.get())
        except ValueError:
            self.cli_state.config(text="端口要填数字。", foreground="#c0392b")
            return
        ok, msg = remote_db.check(self.cli_host.get().strip(), port,
                                  self.cli_token.get().strip())
        if ok:
            # 光测通了不算设好。有人测完直接关窗口，以为成了 ——
            # 下次打开又是「本机管数据」，然后单子就录进自己那份库里了。
            msg += "\n还没保存：选上上面那个圆点，再点下面的「保存」，然后重开软件。"
        self.cli_state.config(text=msg, foreground="#1e8449" if ok else "#c0392b")

    def _check_update(self):
        """手动检查更新。只有客户端（会计那台）有意义。"""
        if not db.is_client():
            messagebox.showinfo(
                "检查更新",
                "这台电脑是数据源头（服务器），不参与自动更新。\n"
                "把新程序文件放到这台电脑上直接双击即可。", parent=self)
            return
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            has_new, sver, info = updater.check_update()
        except Exception as e:
            self.config(cursor="")
            messagebox.showwarning("检查更新", f"连不上服务器：\n{e}", parent=self)
            return
        self.config(cursor="")
        if has_new:
            if messagebox.askyesno(
                    "发现新版本",
                    f"服务器上有新版本 v{sver}（本机 {version.full()}）。\n\n"
                    f"是否现在下载并更新？更新时本程序会自动关闭并重启。",
                    parent=self):
                self.destroy()
                self.master._do_update(sver, info)
        else:
            messagebox.showinfo("检查更新", f"已是最新版本（{version.full()}）。",
                                parent=self)

    def _refresh_backups(self):
        files = backup.list_backups()
        self.blist.load(files, lambda p: (os.path.basename(p),
                                          f"{os.path.getsize(p) / 1024:.0f} KB"))

    def _do_backup(self):
        if db.is_client():
            messagebox.showinfo("请在服务器操作",
                                "当前数据在服务器上，请到服务器电脑点击立即备份。",
                                parent=self)
            return
        path = backup.backup_now("manual")
        self._refresh_backups()
        messagebox.showinfo("备份完成", f"已备份到：\n{path}", parent=self)

    def _do_restore(self):
        if db.is_client():
            messagebox.showinfo("请在服务器操作",
                                "客户端不能恢复服务器数据库。", parent=self)
            return
        path = self.blist.current()
        if not path:
            messagebox.showinfo("提示", "请先选中一个备份文件", parent=self)
            return
        if not messagebox.askyesno(
                "确认恢复", f"用以下备份覆盖当前数据？\n\n{os.path.basename(path)}\n\n"
                            f"当前数据会先自动备份一份。恢复后程序将关闭，请重新打开。",
                parent=self):
            return
        backup.restore(path)
        messagebox.showinfo("恢复完成", "数据已恢复，程序即将关闭，请重新启动。", parent=self)
        self.master.destroy()

    def _open_dir(self):
        os.makedirs(backup.BACKUP_DIR, exist_ok=True)
        os.startfile(backup.BACKUP_DIR)

    def _merge_database(self):
        if db.is_client():
            messagebox.showinfo("请在服务器操作",
                                "只有管理数据的服务器电脑可以合并数据库。",
                                parent=self)
            return
        path = filedialog.askopenfilename(
            parent=self, title="选择另一台电脑复制出来的数据库",
            filetypes=[("ERP 数据库", "*.db"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            report = db_merge.analyze_database(path)
        except Exception as e:
            messagebox.showerror("无法预览", str(e), parent=self)
            return
        dialog = MergePreviewWindow(self, report)
        if not dialog.result:
            return
        try:
            result = db_merge.merge_database(
                path, report.confirmation_key(), report.fingerprint)
        except Exception as e:
            messagebox.showerror("合并失败", "%s\n\n服务器数据未被改变。" % e,
                                 parent=self)
            return
        self._refresh_backups()
        if hasattr(self.master, "refresh"):
            self.master.refresh()
        log = "\n合并日志：%s" % result.log_path if result.log_path else ""
        messagebox.showinfo(
            "合并完成",
            "已新增 %d 条数据。\n合并前备份：%s%s" %
            (result.report.total_added, result.backup_path, log), parent=self)

    def save(self):
        for key in self.vars:
            set_setting(key, self.vars[key].get().strip())
        set_setting("billing_basis", self.basis.get())
        for key, var, default in (("shrink_warn_pct", self.shrink, "8"),
                                  ("backup_keep", self.keep, "30")):
            try:
                float(var.get())
                set_setting(key, var.get().strip())
            except ValueError:
                set_setting(key, default)

        # 皮肤：把显示名映射回 key 存进设置
        skin_key = "default"
        for k, (nm, _c) in SKINS.items():
            if nm == self.skin_name.get():
                skin_key = k
                break
        set_setting("skin", skin_key)

        try:
            tip = self._save_net()
        except Exception as e:
            # 网络这一项没存住必须当场说清楚 —— 不然会计以为改好了，
            # 重启一看还是「本机管数据」，之后录的单子全进了他自己那份库，
            # 两套账各记一半，对账时才发现。
            messagebox.showerror(
                "多人共用设置没保存成功",
                "别的设置已经存好了，但「多人共用/手机」这一项没能存住：\n\n"
                "%s\n\n重启软件后这台电脑还是原来的角色，先别用来录数据。"
                % e, parent=self)
            return
        messagebox.showinfo("已保存", "设置已保存。" + tip, parent=self)
        self.destroy()

    def _save_net(self):
        """存网络设置。返回要不要提示重启。"""
        was_client = db.is_client()
        if self.role.get() == "client":
            host = self.cli_host.get().strip()
            if not host:
                return "\n\n（「连别人的电脑」没填地址，这一项没保存。）"
            try:
                port = int(self.cli_port.get())
            except ValueError:
                port = 8756
            db.save_client_config(host, port, self.cli_token.get().strip())
            # 立刻按文件里的内容重新判一次，确认真的切过去了
            if not db.is_client():
                raise OSError("写完了但读回来还是「本机管数据」，"
                              "这个目录可能不允许写。")
            return ("\n\n这台电脑改成了「连 %s 的数据」，重启软件后生效。"
                    % host) if not was_client else "\n\n重启软件后生效。"

        # 选的是「这台电脑管数据」：把客户端配置停掉，免得下次启动又连出去
        if was_client:
            cfg = db._client_config() or {}
            db.save_client_config(cfg.get("host", ""), cfg.get("port", 8756),
                                  cfg.get("token", ""), enabled=False)
        set_setting("server_enabled", "1" if self.srv_on.get() else "0")
        try:
            set_setting("server_port", int(self.srv_port.get()))
        except ValueError:
            pass
        # 开机自启动：写进 Windows 注册表（只在打包成 exe 时生效）
        set_setting("autostart_enabled", "1" if self.autostart_on.get() else "0")
        from .. import autostart
        if not autostart.set_enabled(self.autostart_on.get()):
            if self.autostart_on.get():
                return "\n\n（开机自启动没设上：开发模式没有 exe，打包后才会生效。）"
        return "\n\n这台电脑改成了「管数据」，重启软件后生效。" if was_client else ""
