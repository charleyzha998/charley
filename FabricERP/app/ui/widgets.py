"""可复用 UI 组件：可编辑表格、自动补全输入、日期输入、格式化工具。"""

import calendar
import re
import tkinter as tk
from datetime import date, timedelta
from tkinter import ttk

from .. import db

FONT = ("Microsoft YaHei UI", 10)
FONT_BOLD = ("Microsoft YaHei UI", 10, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 14, "bold")
FONT_BIG = ("Microsoft YaHei UI", 11)

# 列最窄能拖到多少。ttk 默认 20，但它不让你拖到比表头文字还窄 ——
# 「面料名称」四个字就占掉七八十像素，所以显式给一个小值，
# 想把这一列缩成一条也行（拖窄了看不全，鼠标停上去有完整内容）。
MIN_COL_W = 24


# 界面皮肤：名字 -> (显示名, 强调色)。强调色为 None 表示用系统原生外观。
SKINS = {
    "default": ("系统默认", None),
    "blue": ("蓝色", "#1f6feb"),
    "green": ("绿色", "#1e8449"),
    "purple": ("紫色", "#7d3c98"),
    "orange": ("橙色", "#d35400"),
}


def _darken(hex_color, factor=0.82):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (max(0, int(c * factor)) for c in (r, g, b))
    return "#%02x%02x%02x" % (r, g, b)


def setup_style(root):
    root.option_add("*Font", FONT)
    style = ttk.Style(root)
    try:
        skin = db.get_setting("skin", "default")
    except Exception:
        skin = "default"
    _label, accent = SKINS.get(skin, SKINS["default"])

    # 有强调色就用 clam（能上色）；否则用 vista（原生 Windows 外观）
    try:
        style.theme_use("clam" if accent else "vista")
    except tk.TclError:
        pass

    style.configure("Treeview", rowheight=26, font=FONT)
    style.configure("TButton", padding=(10, 4))
    style.configure("TNotebook.Tab", padding=(18, 7), font=FONT_BIG)
    style.configure("Total.TLabel", font=("Microsoft YaHei UI", 11, "bold"))
    style.configure("Title.TLabel", font=FONT_TITLE)
    style.configure("Warn.TLabel", foreground="#c00000")

    if accent:
        style.configure("Treeview.Heading", background=accent, foreground="white",
                        font=FONT_BOLD, relief="flat")
        style.map("Treeview.Heading", background=[("active", _darken(accent))])
        style.map("Treeview", background=[("selected", accent)])
        style.configure("Accent.TButton", background=accent, foreground="white",
                        font=FONT_BOLD, borderwidth=0, focusthickness=0)
        style.map("Accent.TButton",
                  background=[("active", _darken(accent)),
                              ("pressed", _darken(accent, 0.7))])
        style.configure("Title.TLabel", foreground=accent)
        style.map("TNotebook.Tab",
                  background=[("selected", accent)],
                  foreground=[("selected", "white")])
    else:
        style.configure("Treeview.Heading", font=FONT_BOLD)
        style.configure("Accent.TButton", font=FONT_BOLD)

    _apply_icon(root)


def _apply_icon(root):
    """给窗口设图标（取 exe 同级的 icon.ico，没有就跳过）。"""
    try:
        from .. import tray
        p = tray.icon_file()
        if p:
            root.iconbitmap(p)
    except Exception:
        pass


def fmt_money(x):
    return f"{float(x or 0):,.2f}"


def fmt_meters(x):
    return f"{float(x or 0):,.2f}"


def parse_num(s, default=0.0):
    if s is None:
        return default
    s = str(s).strip().replace(",", "")
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        raise ValueError(f"「{s}」不是有效数字")


def parse_int(s, default=0):
    v = parse_num(s, default)
    if abs(v - round(v)) > 1e-6:
        raise ValueError(f"「{s}」必须是整数")
    return int(round(v))


DATE_RE = re.compile(r"^(\d{4})[-/.]?(\d{1,2})[-/.]?(\d{1,2})$")


def parse_date(s):
    """接受 2026-08-13 / 2026/8/13 / 20260813 / 0813 / 13。"""
    s = (s or "").strip()
    if not s:
        return None
    today = date.today()
    if s in ("今天", "today", "t"):
        return today.strftime("%Y-%m-%d")
    if s.isdigit() and len(s) <= 2:
        return today.replace(day=int(s)).strftime("%Y-%m-%d")
    if s.isdigit() and len(s) == 4:
        return date(today.year, int(s[:2]), int(s[2:])).strftime("%Y-%m-%d")
    m = DATE_RE.match(s)
    if m:
        y, mo, d = (int(g) for g in m.groups())
        return date(y, mo, d).strftime("%Y-%m-%d")
    raise ValueError(f"日期格式不对：{s}（应为 2026-08-13）")


def month_range(offset=0):
    """返回 (本月首日, 本月末日)，offset=-1 是上月。"""
    today = date.today()
    y, m = today.year, today.month + offset
    while m < 1:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    first = date(y, m, 1)
    nxt = date(y + (m == 12), (m % 12) + 1, 1)
    return first.strftime("%Y-%m-%d"), (nxt - timedelta(days=1)).strftime("%Y-%m-%d")


class DateEntry(ttk.Frame):
    """日期输入框：失焦自动规范化，右侧「今」按钮填今天。"""

    def __init__(self, master, value=None, width=12, **kw):
        super().__init__(master, **kw)
        # value=None 默认今天；value="" 表示留空（用作「不限日期」的筛选框）
        if value is None:
            value = date.today().strftime("%Y-%m-%d")
        self.var = tk.StringVar(value=value)
        self.entry = ttk.Entry(self, textvariable=self.var, width=width)
        self.entry.pack(side="left")
        ttk.Button(self, text="选", width=3, command=self._pick).pack(side="left", padx=(2, 0))
        ttk.Button(self, text="今", width=3, command=self.set_today).pack(side="left", padx=(2, 0))
        self.entry.bind("<FocusOut>", self._normalize)

    def _normalize(self, _=None):
        try:
            v = parse_date(self.var.get())
            if v:
                self.var.set(v)
        except ValueError:
            pass

    def set_today(self):
        self.var.set(date.today().strftime("%Y-%m-%d"))

    def _pick(self):
        """弹出中文月历选日期，选中回填到输入框。"""
        try:
            initial = parse_date(self.var.get()) or date.today().strftime("%Y-%m-%d")
        except ValueError:
            initial = date.today().strftime("%Y-%m-%d")
        y, m, d = (int(x) for x in initial.split("-"))
        dlg = DatePicker(self, date(y, m, d))
        if dlg.result is not None:
            self.var.set(dlg.result)

    def get(self):
        return parse_date(self.var.get())

    def set(self, v):
        self.var.set(v or "")


class DatePicker(tk.Toplevel):
    """中文月历选日期弹窗。点选返回 YYYY-MM-DD，「清除」返回空串，取消返回 None。"""

    WEEKDAYS = ("一", "二", "三", "四", "五", "六", "日")

    def __init__(self, master, initial=None):
        super().__init__(master)
        self.title("选择日期")
        self.resizable(False, False)
        self.result = None
        self._today = date.today()
        if initial is None:
            initial = self._today
        self._selected = initial
        self._cur = date(initial.year, initial.month, 1)
        self._build()
        self.transient(master.winfo_toplevel())
        self.grab_set()
        try:
            x = master.winfo_rootx()
            y = master.winfo_rooty() + master.winfo_height() + 4
            self.geometry("+%d+%d" % (x, y))
        except Exception:
            pass
        self.wait_window()

    def _build(self):
        head = ttk.Frame(self, padding=(10, 10, 10, 4))
        head.pack(fill="x")
        ttk.Button(head, text="‹", width=3, command=self._prev).pack(side="left")
        self.title_lbl = ttk.Label(head, text="", width=12, anchor="center",
                                    font=FONT_BOLD)
        self.title_lbl.pack(side="left", padx=8)
        ttk.Button(head, text="›", width=3, command=self._next).pack(side="left")
        ttk.Button(head, text="今天", command=self._today_btn).pack(side="right")

        wk = ttk.Frame(self, padding=(10, 2))
        wk.pack(fill="x")
        for i, name in enumerate(self.WEEKDAYS):
            ttk.Label(wk, text=name, width=4, anchor="center",
                      foreground="#666").grid(row=0, column=i)

        self.cal = ttk.Frame(self, padding=(10, 0, 10, 4))
        self.cal.pack(fill="both", expand=True)

        foot = ttk.Frame(self, padding=(10, 0, 10, 10))
        foot.pack(fill="x")
        ttk.Button(foot, text="清除", command=self._clear).pack(side="left")
        ttk.Button(foot, text="取消", command=self.destroy).pack(side="right")

        self._draw()

    def _draw(self):
        for w in self.cal.winfo_children():
            w.destroy()
        self.title_lbl.config(text="%d 年 %d 月" % (self._cur.year, self._cur.month))
        cal = calendar.Calendar(firstweekday=0)      # 周一开头
        for r, week in enumerate(cal.monthdayscalendar(self._cur.year, self._cur.month)):
            for c, day in enumerate(week):
                if day == 0:
                    ttk.Label(self.cal, text="", width=4).grid(row=r, column=c, padx=1, pady=1)
                    continue
                d = date(self._cur.year, self._cur.month, day)
                btn = tk.Button(self.cal, text=str(day), width=4, relief="flat",
                                command=lambda d=d: self._choose(d))
                if d == self._today:
                    btn.configure(bg="#1f6feb", fg="white", relief="solid")
                elif d == self._selected:
                    btn.configure(bg="#dbe7f6")
                btn.grid(row=r, column=c, padx=1, pady=1)

    def _choose(self, d):
        self.result = d.strftime("%Y-%m-%d")
        self.destroy()

    def _clear(self):
        self.result = ""
        self.destroy()

    def _today_btn(self):
        self._choose(self._today)

    def _prev(self):
        y, m = self._cur.year, self._cur.month - 1
        if m == 0:
            y, m = y - 1, 12
        self._cur = date(y, m, 1)
        self._draw()

    def _next(self):
        y, m = self._cur.year, self._cur.month + 1
        if m == 13:
            y, m = y + 1, 1
        self._cur = date(y, m, 1)
        self._draw()


class AutocompleteCombobox(ttk.Combobox):
    """输入即过滤的下拉框，允许输入表中没有的新值。"""

    def __init__(self, master, values=None, **kw):
        super().__init__(master, **kw)
        self.set_completion_list(values or [])
        self.bind("<KeyRelease>", self._on_key)

    def set_completion_list(self, values):
        self._all = list(values)
        self["values"] = self._all

    def _on_key(self, event):
        if event.keysym in ("BackSpace", "Delete", "Left", "Right", "Up", "Down",
                            "Return", "Tab", "Escape"):
            return
        text = self.get()
        if not text:
            self["values"] = self._all
            return
        hits = [v for v in self._all if text.lower() in str(v).lower()]
        self["values"] = hits or self._all


class _CellTip:
    """鼠标停在格子上，显示这一格的完整内容。

    列拖窄以后字会被切成「盛泽阿提335尼…」，光看表格认不出是哪个货。
    只在真的显示不全时才弹 —— 每个格子都弹反而烦。
    """

    DELAY = 500          # 停多久才弹，单位毫秒

    def __init__(self, tree):
        self.tree = tree
        self.tip = None
        self.cell = None
        self.job = None
        tree.bind("<Motion>", self._move, add="+")
        tree.bind("<Leave>", lambda e: self._hide(), add="+")
        tree.bind("<Button-1>", lambda e: self._hide(), add="+")

    def _move(self, ev):
        cell = (self.tree.identify_row(ev.y), self.tree.identify_column(ev.x))
        if cell == self.cell:
            return
        self.cell = cell
        self._hide()
        if not cell[0] or not cell[1]:
            return
        if self.job:
            self.tree.after_cancel(self.job)
        self.job = self.tree.after(self.DELAY, lambda: self._show(ev.x_root,
                                                                 ev.y_root))

    def _show(self, x, y):
        self.job = None
        row, col = self.cell
        try:
            text = str(self.tree.set(row, col) or "")
        except Exception:
            return                       # 行没了（刷新过）
        if not text.strip():
            return
        # 装得下就不弹。一个汉字约等于字号那么宽，英文数字约一半。
        width = self.tree.column(col, "width")
        need = sum(13 if ord(ch) > 127 else 7 for ch in text) + 10
        if need <= width:
            return
        self.tip = tk.Toplevel(self.tree)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry("+%d+%d" % (x + 12, y + 16))
        tk.Label(self.tip, text=text, justify="left", background="#ffffe0",
                 relief="solid", borderwidth=1, font=FONT,
                 padx=6, pady=3).pack()

    def _hide(self):
        if self.job:
            self.tree.after_cancel(self.job)
            self.job = None
        if self.tip:
            self.tip.destroy()
            self.tip = None


class EditableGrid(ttk.Frame):
    """可编辑明细表格 —— 明细录入的核心组件。

    columns: [{key, title, width, type: 'text'|'int'|'float'|'money'|'combo'|'readonly',
               values: [...] (combo), anchor}]
    双击/回车进入编辑，Tab 跳下一格，最后一行 Tab 自动加行。
    on_change(row_index, key, value) 回调用于联动（选缸号带出面料等）。
    """

    def __init__(self, master, columns, on_change=None, min_rows=1, **kw):
        super().__init__(master, **kw)
        self.columns = columns
        self.on_change = on_change
        self.min_rows = min_rows
        self._rows = []          # [{key: value}]，另含 '_id' 等隐藏字段
        self._editor = None
        self._edit_pos = None

        keys = [c["key"] for c in columns]
        self.tree = ttk.Treeview(self, columns=keys, show="headings", selectmode="browse")
        for c in columns:
            self.tree.heading(c["key"], text=c["title"])
            self.tree.column(c["key"], width=c.get("width", 90),
                             minwidth=c.get("minwidth", MIN_COL_W),
                             anchor=c.get("anchor", "center"),
                             stretch=c.get("stretch", False))
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.tree.bind("<Double-1>", self._begin_edit_event)
        self.tree.bind("<Return>", self._begin_edit_event)
        self.tree.bind("<Delete>", lambda e: self.delete_current())

        for _ in range(min_rows):
            self.add_row()

    # ---- 数据存取 ----

    def add_row(self, data=None):
        row = {c["key"]: "" for c in self.columns}
        row.update(data or {})
        self._rows.append(row)
        self.tree.insert("", "end", values=self._display(row))
        return len(self._rows) - 1

    def set_rows(self, rows):
        self.cancel_edit()
        self._rows = []
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            self.add_row(r)
        while len(self._rows) < self.min_rows:
            self.add_row()

    def get_rows(self, skip_empty_key=None):
        """返回原始 dict 列表。skip_empty_key 指定的字段为空则跳过该行。"""
        out = []
        for r in self._rows:
            if skip_empty_key and not str(r.get(skip_empty_key, "")).strip():
                continue
            out.append(dict(r))
        return out

    def update_row(self, idx, data):
        self._rows[idx].update(data)
        iid = self.tree.get_children()[idx]
        self.tree.item(iid, values=self._display(self._rows[idx]))

    def get_row(self, idx):
        return self._rows[idx]

    def current_index(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self.tree.index(sel[0])

    def delete_current(self):
        idx = self.current_index()
        if idx is None:
            return
        self.cancel_edit()
        self._rows.pop(idx)
        self.tree.delete(self.tree.get_children()[idx])
        if not self._rows:
            self.add_row()

    def _display(self, row):
        out = []
        for c in self.columns:
            v = row.get(c["key"], "")
            t = c.get("type")
            if v == "" or v is None:
                out.append("")
            elif t in ("money",):
                out.append(fmt_money(v))
            elif t == "float":
                out.append(fmt_meters(v))
            else:
                out.append(str(v))
        return out

    # ---- 编辑 ----

    def _begin_edit_event(self, event):
        if event.type == tk.EventType.ButtonPress:
            iid = self.tree.identify_row(event.y)
            col = self.tree.identify_column(event.x)
            if not iid or not col:
                return
            r, c = self.tree.index(iid), int(col[1:]) - 1
        else:
            idx = self.current_index()
            if idx is None:
                return
            r, c = idx, 0
        self.begin_edit(r, c)
        return "break"

    def begin_edit(self, r, c):
        self.cancel_edit()
        if r >= len(self._rows):
            return
        while c < len(self.columns) and self.columns[c].get("type") == "readonly":
            c += 1
        if c >= len(self.columns):
            return

        col = self.columns[c]
        iid = self.tree.get_children()[r]
        self.tree.selection_set(iid)
        self.tree.see(iid)
        x, y, w, h = self.tree.bbox(iid, self.tree["columns"][c])

        val = self._rows[r].get(col["key"], "")
        # Treeview 的 anchor(e/w/center) 与 Entry 的 justify(left/right/center) 取值不同
        justify = {"e": "right", "w": "left"}.get(col.get("anchor"), "center")
        if col.get("type") == "combo":
            ed = AutocompleteCombobox(self.tree, values=col.get("values", []),
                                      justify=justify)
            ed.set(str(val))
        else:
            ed = ttk.Entry(self.tree, justify=justify)
            ed.insert(0, str(val))
            ed.select_range(0, "end")
        ed.place(x=x, y=y, width=w, height=h)
        ed.focus_set()
        ed.bind("<Return>", lambda e: self._commit(move="down"))
        ed.bind("<Tab>", lambda e: self._commit(move="right"))
        ed.bind("<Escape>", lambda e: self.cancel_edit())
        ed.bind("<FocusOut>", lambda e: self._commit(move=None))
        if col.get("type") == "combo":
            ed.bind("<<ComboboxSelected>>", lambda e: self._commit(move="right"))
        self._editor, self._edit_pos = ed, (r, c)

    def _commit(self, move=None):
        if not self._editor:
            return "break"
        r, c = self._edit_pos
        col = self.columns[c]
        raw = self._editor.get()
        self.cancel_edit()

        try:
            if col.get("type") == "int":
                val = parse_int(raw) if str(raw).strip() else ""
            elif col.get("type") in ("float", "money"):
                val = round(parse_num(raw), 2) if str(raw).strip() else ""
            else:
                val = str(raw).strip()
        except ValueError:
            self.bell()
            self.begin_edit(r, c)
            return "break"

        self._rows[r][col["key"]] = val
        self.tree.item(self.tree.get_children()[r], values=self._display(self._rows[r]))
        if self.on_change:
            self.on_change(r, col["key"], val)

        if move == "right":
            nc = c + 1
            while nc < len(self.columns) and self.columns[nc].get("type") == "readonly":
                nc += 1
            if nc < len(self.columns):
                self.begin_edit(r, nc)
            elif r == len(self._rows) - 1:
                self.add_row()
                self.begin_edit(r + 1, 0)
            else:
                self.begin_edit(r + 1, 0)
        elif move == "down":
            if r == len(self._rows) - 1:
                self.add_row()
            self.begin_edit(r + 1, c)
        return "break"

    def cancel_edit(self):
        if self._editor:
            ed, self._editor, self._edit_pos = self._editor, None, None
            ed.destroy()
        return "break"

    def commit_pending(self):
        """保存前调用，确保正在编辑的格子已落值。"""
        if self._editor:
            self._commit(move=None)


class ReadonlyGrid(ttk.Frame):
    """只读列表，带排序、双击回调、行标色。"""

    def __init__(self, master, columns, on_double=None, **kw):
        super().__init__(master, **kw)
        self.columns = columns
        self.on_double = on_double
        keys = [c["key"] for c in columns]
        self.tree = ttk.Treeview(self, columns=keys, show="headings", selectmode="browse")
        for c in columns:
            self.tree.heading(c["key"], text=c["title"],
                              command=lambda k=c["key"]: self._sort(k))
            self.tree.column(c["key"], width=c.get("width", 90),
                             minwidth=c.get("minwidth", MIN_COL_W),
                             anchor=c.get("anchor", "center"),
                             stretch=c.get("stretch", False))
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.tree.tag_configure("warn", background="#fff3cd")
        self.tree.tag_configure("done", foreground="#707070")
        self.tree.tag_configure("debt", foreground="#c00000")
        self.tree.tag_configure("total", font=FONT_BOLD, background="#eef3fb")

        self._sort_desc = {}
        self._data = []
        if on_double:
            self.tree.bind("<Double-1>", lambda e: self._fire())

        # 列拖窄了字会被切掉，鼠标停上去把完整内容显示出来
        self._tip = _CellTip(self.tree)

    def _fire(self):
        idx = self.current_index()
        if idx is not None and idx < len(self._data):
            self.on_double(self._data[idx])

    def load(self, rows, value_fn, tag_fn=None):
        """rows: 数据对象列表；value_fn(row)->tuple；tag_fn(row)->tag 或 None。"""
        self.tree.delete(*self.tree.get_children())
        self._data = list(rows)
        for r in self._data:
            tags = ()
            if tag_fn:
                t = tag_fn(r)
                tags = (t,) if t else ()
            self.tree.insert("", "end", values=value_fn(r), tags=tags)

    def append_total(self, values):
        self.tree.insert("", "end", values=values, tags=("total",))
        self._data.append(None)

    def current(self):
        idx = self.current_index()
        return self._data[idx] if idx is not None and idx < len(self._data) else None

    def current_index(self):
        sel = self.tree.selection()
        return self.tree.index(sel[0]) if sel else None

    def _sort(self, key):
        desc = not self._sort_desc.get(key, False)
        self._sort_desc[key] = desc
        items = [(self.tree.set(k, key), k) for k in self.tree.get_children("")]

        def sk(t):
            s = t[0].replace(",", "")
            try:
                return (0, float(s))
            except ValueError:
                return (1, t[0])

        items.sort(key=sk, reverse=desc)
        data_map = {k: d for k, d in zip(self.tree.get_children(""), self._data)}
        for i, (_, k) in enumerate(items):
            self.tree.move(k, "", i)
        self._data = [data_map[k] for _, k in items]


def labeled(master, text, widget, row, col=0, sticky="w", padx=6, pady=4, width=None):
    """在 grid 布局里放「标签 + 控件」。"""
    lbl = ttk.Label(master, text=text)
    lbl.grid(row=row, column=col * 2, sticky="e", padx=(padx, 2), pady=pady)
    widget.grid(row=row, column=col * 2 + 1, sticky=sticky, padx=(0, padx), pady=pady)
    return widget


class AutoRefresh:
    """隔几秒看一眼库里有没有人动过东西，有就重读。

    为什么需要：两台电脑共用一份库，会计存了单子，我这边屏幕上还是老样子 ——
    数据早到了，只是画面不会自己变。以前得手动切一下标签页，可谁知道什么时候
    该切。

    只查一个整数（data_rev），没变就什么都不做，所以可以问得勤一点。

    有两条不能碰：
    · 弹着单据窗口（进仓单/发货单/收款…）时不刷。正填到一半被冲掉更糟。
      这些窗口都调了 grab_set，所以用 grab_current() 就能认出来。
    · 自己存东西也会让 data_rev 变。存完顺手记下新值，免得白刷一轮。
    """
    POLL_MS = 4000

    def start_auto(self, on_change):
        self._auto_cb = on_change
        self._auto_rev = db.data_rev()
        self._auto_job = None
        self._auto_tick()

    def _auto_tick(self):
        self._auto_job = None
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        try:
            # 弹着对话框就跳过这一轮
            if self.grab_current() is None:
                rev = db.data_rev()
                if rev >= 0 and rev != self._auto_rev:
                    self._auto_rev = rev
                    self._auto_cb()
        except Exception:
            # 网络断了之类的：这一轮算了，下一轮再试。别弹错误框，
            # 用户什么都没点，凭空弹一个框只会让人以为坏了。
            pass
        try:
            self._auto_job = self.after(self.POLL_MS, self._auto_tick)
        except Exception:
            pass

    def note_own_change(self):
        """自己刚存过东西 —— 把版本号记成最新的，省一轮无用的重读。"""
        self._auto_rev = db.data_rev()

    def stop_auto(self):
        if getattr(self, "_auto_job", None):
            try:
                self.after_cancel(self._auto_job)
            except Exception:
                pass
            self._auto_job = None


def pin_bottom(bar, above=None):
    """把按钮条钉死在窗口底边。

    pack 是按调用顺序分地方的：内容用了 expand=True，又比按钮条先 pack，
    高度就全归内容，按钮条被挤到窗口外面 —— 屏幕上根本看不见「保存」，
    单子填完存不了（会计那台的设置窗口就是这样，一直以为是没保存住）。
    光加 side="bottom" 不管用，必须让它排在会膨胀的那块前面，所以要 before=。
    """
    if above is not None:
        bar.pack(side="bottom", fill="x", before=above)
    else:
        bar.pack(side="bottom", fill="x")
    return bar
