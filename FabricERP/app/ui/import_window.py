"""Excel 导入向导：生成模板 → 选文件 → 看校验报告 → 导入。"""

import os
import tkinter as tk
from datetime import date
from tkinter import filedialog, messagebox, ttk

from .. import importer
from .widgets import FONT_BOLD, FONT_TITLE, ReadonlyGrid, setup_style


class ImportWindow(tk.Toplevel):
    def __init__(self, master, on_done=None):
        super().__init__(master)
        self.on_done = on_done
        self.rep = None
        self.path = None
        self.title("从 Excel 导入数据")
        self.geometry("880x600")
        setup_style(self)
        self.transient(master)

        head = ttk.Frame(self, padding=(14, 12, 14, 6))
        head.pack(fill="x")
        ttk.Label(head, text="从 Excel 导入数据", font=FONT_TITLE).pack(anchor="w")
        ttk.Label(head, foreground="#555", justify="left", wraplength=820,
                  text="给会计发一份空白模板，他填好后发回来，在这里选中文件导入。"
                       "会计电脑上不用装本软件。\n"
                       "导入前会先自动备份，并把数据从头到尾检查一遍，"
                       "全部没问题才会真正写入。").pack(anchor="w", pady=(4, 0))

        step = ttk.Frame(self, padding=(14, 10, 14, 6))
        step.pack(fill="x")
        ttk.Button(step, text="① 生成空白模板…", command=self.make_template).pack(side="left")
        ttk.Button(step, text="② 选择填好的文件…", style="Accent.TButton",
                   command=self.pick_file).pack(side="left", padx=8)
        self.file_lbl = ttk.Label(step, text="（还没选文件）", foreground="#888")
        self.file_lbl.pack(side="left", padx=6)

        self.summary = ttk.Label(self, text="", padding=(14, 4), justify="left",
                                 font=FONT_BOLD)
        self.summary.pack(fill="x")

        self.grid = ReadonlyGrid(self, [
            {"key": "level", "title": "", "width": 60},
            {"key": "sheet", "title": "工作表", "width": 80},
            {"key": "row", "title": "行号", "width": 60},
            {"key": "msg", "title": "说明", "width": 620, "anchor": "w", "stretch": True},
        ])
        self.grid.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        btns = ttk.Frame(self, padding=(14, 0, 14, 12))
        btns.pack(fill="x")
        self.go = ttk.Button(btns, text="③ 确认导入", style="Accent.TButton",
                             command=self.do_import, state="disabled")
        self.go.pack(side="right")
        ttk.Button(btns, text="关闭", command=self.destroy).pack(side="right", padx=6)
        self.hint = ttk.Label(btns, text="", foreground="#555")
        self.hint.pack(side="left")
        self.grab_set()

    # ---------- 步骤 ----------

    def make_template(self):
        name = f"导入模板_{date.today():%Y%m%d}.xlsx"
        path = filedialog.asksaveasfilename(
            parent=self, title="保存空白模板", initialfile=name,
            defaultextension=".xlsx", filetypes=[("Excel 文件", "*.xlsx")])
        if not path:
            return
        try:
            importer.write_template(path)
        except PermissionError:
            messagebox.showerror("保存失败", "这个文件正被 Excel 打开，先关掉再试。",
                                 parent=self)
            return
        if messagebox.askyesno("模板已生成",
                               f"已保存到：\n{path}\n\n现在打开看看吗？", parent=self):
            os.startfile(path)

    def pick_file(self):
        path = filedialog.askopenfilename(
            parent=self, title="选择填好的 Excel",
            filetypes=[("Excel 文件", "*.xlsx *.xlsm"), ("所有文件", "*.*")])
        if not path:
            return
        self.path = path
        self.file_lbl.config(text=os.path.basename(path), foreground="#000")
        self.check()

    def check(self):
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            self.rep = importer.analyze(self.path)
        except Exception as e:
            messagebox.showerror("检查失败", f"读这个文件时出错了：\n{e}", parent=self)
            return
        finally:
            self.config(cursor="")

        rep = self.rep
        rows = ([{"level": "错误", "sheet": s, "row": r or "", "msg": m}
                 for s, r, m in rep.errors]
                + [{"level": "提醒", "sheet": s, "row": r or "", "msg": m}
                   for s, r, m in rep.warnings])
        self.grid.load(rows, lambda r: (r["level"], r["sheet"], r["row"], r["msg"]),
                       tag_fn=lambda r: "debt" if r["level"] == "错误" else "warn")

        got = "　".join(f"{k} {v}" for k, v in rep.stats.items() if v)
        extra = []
        if getattr(rep, "new_fabrics", None):
            extra.append(f"将新建面料 {len(rep.new_fabrics)} 种")
        if getattr(rep, "new_processes", None):
            extra.append(f"新建工艺 {len(rep.new_processes)} 种")

        if rep.errors:
            self.summary.config(
                text=f"发现 {len(rep.errors)} 处错误，必须先在 Excel 里改好才能导入。",
                foreground="#c00000")
            self.go.config(state="disabled")
            self.hint.config(text="改完 Excel 后，重新点「② 选择填好的文件」即可。")
        elif not rep.ok:
            self.summary.config(text="这个文件里没有可导入的数据。", foreground="#c00000")
            self.go.config(state="disabled")
            self.hint.config(text="")
        else:
            msg = f"检查通过，可以导入：{got}"
            if extra:
                msg += f"　（{'，'.join(extra)}）"
            self.summary.config(text=msg, foreground="#006400")
            self.go.config(state="normal")
            self.hint.config(
                text=f"{len(rep.warnings)} 条提醒不影响导入，但建议看一眼。"
                if rep.warnings else "没有问题，点右边「确认导入」。")

    def do_import(self):
        rep = self.rep
        got = "\n".join(f"　{k}：{v}" for k, v in rep.stats.items() if v)
        if not messagebox.askyesno(
                "确认导入", f"即将导入以下数据：\n\n{got}\n\n"
                            f"导入前会先自动备份，出问题可以从备份恢复。\n确定吗？",
                parent=self):
            return
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            done = importer.run_import(rep)
        except Exception as e:
            messagebox.showerror("导入失败",
                                 f"导入过程中出错，数据已全部回滚，"
                                 f"库里没有留下半截数据。\n\n{e}", parent=self)
            return
        finally:
            self.config(cursor="")
        detail = "\n".join(f"　{k}：{v}" for k, v in done.items() if v)
        messagebox.showinfo("导入完成", f"已导入：\n\n{detail}", parent=self)
        if self.on_done:
            self.on_done()
        self.destroy()
