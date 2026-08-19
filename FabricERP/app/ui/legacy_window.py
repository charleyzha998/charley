"""老账本导入向导：选文件夹 → 自动认表 → 看问题清单 → 导入。

跟「从 Excel 导入」不同的是：那个走统一模板，这个直接吃手写的老账本，
每个客户一套规则。所以这里的重点是**先让人看清认出了什么、哪几行有问题**，
再决定要不要导。
"""

import os
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import legacy_commit, legacy_import
from .widgets import FONT_BOLD, FONT_TITLE, ReadonlyGrid, setup_style

# 一个客户可能要好几个文件一起看（鹏川的进仓和对账分开记；
# 龚松权的入库表要靠发货表才能推出期初库存）。这里定死配对关系。
JOBS = [
    {"customer": "鹏川纺织", "files": ("入库", "对账"), "kind": "pengchuan"},
    {"customer": "逸峰纺织", "files": ("逸峰",), "kind": "yifeng"},
    {"customer": "龚松权", "files": ("入库", "发货"), "kind": "gongsongquan"},
]


class LegacyWindow(tk.Toplevel):
    def __init__(self, master, on_done=None):
        super().__init__(master)
        self.on_done = on_done
        self.folder = None
        self.plans = []          # [{customer, result, files, kind}]
        self.title("导入老账本")
        self.geometry("960x640")
        setup_style(self)
        self.transient(master)

        head = ttk.Frame(self, padding=(14, 12, 14, 6))
        head.pack(fill="x")
        ttk.Label(head, text="导入老账本", font=FONT_TITLE).pack(anchor="w")
        ttk.Label(head, foreground="#555", justify="left", wraplength=900,
                  text="选中放账本的文件夹，软件会自己认出是哪个客户的哪张表，"
                       "按各自的记法读进来。\n"
                       "读完先看下面的清单：写「提醒」的地方是账本本身有出入"
                       "（日期写错、合计对不上之类），不影响导入，但建议回去核一下。"
                  ).pack(anchor="w", pady=(4, 0))

        step = ttk.Frame(self, padding=(14, 10, 14, 6))
        step.pack(fill="x")
        ttk.Button(step, text="① 选择账本文件夹…", style="Accent.TButton",
                   command=self.pick_folder).pack(side="left")
        self.file_lbl = ttk.Label(step, text="（还没选）", foreground="#888")
        self.file_lbl.pack(side="left", padx=8)

        self.summary = ttk.Label(self, text="", padding=(14, 4), justify="left",
                                 font=FONT_BOLD)
        self.summary.pack(fill="x")

        self.grid = ReadonlyGrid(self, [
            {"key": "level", "title": "", "width": 56},
            {"key": "customer", "title": "客户", "width": 90},
            {"key": "msg", "title": "说明", "width": 740, "anchor": "w",
             "stretch": True},
        ])
        self.grid.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        btns = ttk.Frame(self, padding=(14, 0, 14, 12))
        btns.pack(fill="x")
        self.go = ttk.Button(btns, text="② 确认导入", style="Accent.TButton",
                             command=self.do_import, state="disabled")
        self.go.pack(side="right")
        ttk.Button(btns, text="关闭", command=self.destroy).pack(side="right", padx=6)
        self.hint = ttk.Label(btns, text="", foreground="#555")
        self.hint.pack(side="left")
        self.grab_set()

    # ---------- 步骤 ----------

    def pick_folder(self):
        d = filedialog.askdirectory(parent=self, title="选择放账本的文件夹")
        if not d:
            return
        self.folder = d
        self.file_lbl.config(text=d, foreground="#000")
        self.scan()

    def _find(self, *keys):
        """在文件夹里按关键字找账本。找不到返回 None。"""
        for name in sorted(os.listdir(self.folder)):
            if not name.lower().endswith((".xls", ".xlsx")):
                continue
            if name.startswith("~$"):        # Excel 打开时的临时文件
                continue
            if all(k in name for k in keys):
                return os.path.join(self.folder, name)
        return None

    def scan(self):
        self.config(cursor="watch")
        self.update_idletasks()
        self.plans = []
        rows = []
        try:
            for job in JOBS:
                try:
                    plan = self._parse_job(job)
                except Exception as e:
                    rows.append({"level": "错误", "customer": job["customer"],
                                 "msg": "读这个客户的账本时出错：%s" % e})
                    continue
                if plan is None:
                    continue
                self.plans.append(plan)
                res = plan["result"]
                for m in res.report.errors:
                    rows.append({"level": "错误", "customer": plan["customer"],
                                 "msg": m})
                for m in _group(res.report.warnings):
                    rows.append({"level": "提醒", "customer": plan["customer"],
                                 "msg": m})
        finally:
            self.config(cursor="")

        self.grid.load(rows, lambda r: (r["level"], r["customer"], r["msg"]),
                       tag_fn=lambda r: "debt" if r["level"] == "错误" else "warn")
        self._summarize(rows)

    def _parse_job(self, job):
        """读一个客户的账本。文件不全就跳过（返回 None）。"""
        kind = job["kind"]
        if kind == "pengchuan":
            f_in, f_st = self._find("鹏川", "入库"), self._find("鹏川", "对账")
            if not (f_in and f_st):
                return None
            a = legacy_import.PengchuanInboundRule().parse(
                legacy_import.read_sheets(f_in))
            b = legacy_import.PengchuanStatementRule().parse(
                legacy_import.read_sheets(f_st))
            # 发货要挂到成品上，成品库存才扣得下来
            legacy_import.pc_link_ship(a, b)
            return {"customer": job["customer"], "kind": kind,
                    "result": _merge(a, b), "files": [f_in, f_st],
                    "parts": [a, b]}

        if kind == "yifeng":
            f = self._find("逸峰")
            if not f:
                return None
            r = legacy_import.YifengRule().parse(legacy_import.read_sheets(f))
            return {"customer": job["customer"], "kind": kind, "result": r,
                    "files": [f], "parts": [r]}

        if kind == "gongsongquan":
            f_in = self._find("龚松权", "入库")
            f_sh = self._find("龚松权", "发货")
            if not (f_in and f_sh):
                return None
            r = legacy_import.gs_parse_pair(legacy_import.read_sheets(f_in),
                                            legacy_import.read_sheets(f_sh))
            return {"customer": job["customer"], "kind": kind, "result": r,
                    "files": [f_in, f_sh], "parts": [r]}
        return None

    def _summarize(self, rows):
        if not self.plans:
            self.summary.config(
                text="这个文件夹里没找到认得出的账本。", foreground="#c00000")
            self.go.config(state="disabled")
            self.hint.config(text="账本文件名里要带客户名，比如「鹏川纺织入库明细.xlsx」。")
            return
        parts = []
        for p in self.plans:
            got = "　".join("%s %d" % (k, v) for k, v in p["result"].stats.items() if v)
            parts.append("%s：%s" % (p["customer"], got or "没有数据"))
        errs = sum(1 for r in rows if r["level"] == "错误")
        warns = len(rows) - errs
        self.summary.config(text="认出 %d 个客户的账本　|　%s"
                                 % (len(self.plans), "；".join(parts)),
                            foreground="#c00000" if errs else "#006400")
        self.go.config(state="disabled" if errs else "normal")
        if errs:
            self.hint.config(text="有 %d 处读不出来的地方，先处理掉再导。" % errs)
        else:
            self.hint.config(
                text="%d 条提醒不影响导入，导完请照着清单核一遍账本。" % warns
                if warns else "没有问题，点右边「确认导入」。")

    def do_import(self):
        detail = "\n".join(
            "　%s：%s" % (p["customer"],
                          "　".join("%s %d" % (k, v)
                                    for k, v in p["result"].stats.items() if v))
            for p in self.plans)
        if not messagebox.askyesno(
                "确认导入", "即将导入以下老账本数据：\n\n%s\n\n"
                            "导入前会自动备份现有数据库，出问题可以照备份还原。\n"
                            "每张单子都会写上来自账本哪张表第几行，方便以后回查。\n"
                            "确定吗？" % detail, parent=self):
            return

        self.config(cursor="watch")
        self.update_idletasks()
        done, warns, backup = [], [], ""
        try:
            for p in self.plans:
                # 鹏川分两个文件导：加工在入库明细里，发货在对账明细里，
                # 靠同一个 prod_ids 把发货挂到成品上。
                pids = {}
                for part in p["parts"]:
                    rep = legacy_commit.commit(part, p["customer"], prod_ids=pids)
                    backup = backup or rep.backup
                    done.append("%s：%s" % (p["customer"], rep.summary))
                    warns.extend(rep.warnings)
                    for what, why in rep.skipped:
                        warns.append("跳过 %s —— %s" % (what, why))
        except Exception as e:
            messagebox.showerror(
                "导入失败", "导入过程中出错了：\n\n%s\n\n"
                            "已经导进去的部分留在库里。要从头来的话，"
                            "用导入前的备份还原：\n%s" % (e, backup or "（没有备份）"),
                parent=self)
            return
        finally:
            self.config(cursor="")

        msg = "\n".join(done)
        if warns:
            msg += "\n\n有 %d 条要留意的（比如账本上超发、缸号对不上），" \
                   "已经写进各自单据的备注里。" % len(warns)
        if backup:
            msg += "\n\n导入前的备份：\n%s" % backup
        messagebox.showinfo("导入完成", msg, parent=self)
        if self.on_done:
            self.on_done()
        self.destroy()


def _group(warnings):
    """同一类提醒合成一条，后面缀上「共 N 处」和前几个位置。

    鹏川 4月份整月没写日期和产品名，逐行报就是 118 条，人根本翻不动。
    一类一条 + 说清有多少处、头几处在哪儿，才看得出该不该管。
    """
    order, bag = [], {}
    for w in warnings:
        # 「[4月份] 第59行 账本没写发货日期，暂记为…」→ 位置和说明分开
        head, sep, tail = w.partition("行 ")
        if sep and "第" in head:
            where, what = head.strip(), tail
        else:
            where, what = "", w
        if what not in bag:
            order.append(what)
            bag[what] = []
        bag[what].append(where)

    out = []
    for what in order:
        spots = [x for x in bag[what] if x]
        if len(bag[what]) == 1:
            out.append((spots[0] + "行 " if spots else "") + what)
            continue
        head = "、".join(spots[:3]) + ("等" if len(spots) > 3 else "")
        out.append("%s（共 %d 处：%s）" % (what, len(bag[what]), head))
    return out


def _merge(*results):
    """把同一个客户的几份解析结果并成一份，**只为了界面上显示合计和问题清单**。

    真正导入还是各份分开 commit —— 鹏川的发货要挂到前一份的成品上。
    所以这里必须另建一个对象：直接往 results[0] 里塞，那份就被污染了，
    导入时会把第二份的数据重复算一遍。
    """
    out = legacy_import.ParseResult(results[0].customer,
                                    use_dye_lot=results[0].use_dye_lot)
    for r in results:
        out.inbounds.extend(r.inbounds)
        out.productions.extend(r.productions)
        out.shipments.extend(r.shipments)
        out.prices.extend(r.prices)
        out.payments.extend(r.payments)
        out.report.errors.extend(r.report.errors)
        out.report.warnings.extend(r.report.warnings)
        if r.opening_debt and not out.opening_debt:
            out.opening_debt = r.opening_debt
            out.opening_note = r.opening_note
    return out
