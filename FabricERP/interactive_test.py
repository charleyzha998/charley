"""交互测试：模拟真实录入操作（编辑格子、联动带出、超发确认、保存）。

用法：python interactive_test.py
"""

import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import db  # noqa: E402

_tmp = tempfile.mkdtemp(prefix="ferp_it_")
db.DATA_DIR = _tmp
db.DB_PATH = os.path.join(_tmp, "test.db")

import tkinter as tk  # noqa: E402
from tkinter import messagebox  # noqa: E402

from app import models, services  # noqa: E402

PASS, FAIL = 0, 0


def check(label, actual, expect):
    global PASS, FAIL
    ok = actual == expect
    if isinstance(expect, float) or isinstance(actual, float):
        try:
            ok = abs(float(actual) - float(expect)) < 0.005
        except (TypeError, ValueError):
            ok = False
    if ok:
        PASS += 1
        print(f"  OK   {label} = {actual}")
    else:
        FAIL += 1
        print(f"  FAIL {label} = {actual!r}, 期望 {expect!r}")


def edit_cell(grid, r, c, text):
    """模拟：双击进格子 → 输入 → 回车提交。"""
    grid.begin_edit(r, c)
    ed = grid._editor
    assert ed is not None, f"格子 ({r},{c}) 无法进入编辑"
    ed.delete(0, "end")
    ed.insert(0, str(text))
    grid._commit(move=None)


def main():
    cid = models.save_customer({"name": "宁波华丰针织", "opening_balance": 0})
    fid = models.get_or_create_fabric("涤纶四面弹")
    pid_dye = [p["id"] for p in models.list_processes() if p["name"] == "贴白膜"][0]
    pid_set = [p["id"] for p in models.list_processes() if p["name"] == "贴黑膜"][0]
    models.save_price(cid, fid, pid_dye, 3.5, "2026-01-01")
    models.save_price(cid, None, pid_set, 1.2, "2026-01-01")   # 通用价

    root = tk.Tk()
    root.withdraw()

    answers = {"yes": True}
    messagebox.askyesno = lambda *a, **k: answers["yes"]
    messagebox.showwarning = lambda *a, **k: None
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: print("       [弹窗-错误]", a)

    # 让对话框不阻塞
    orig_wait, orig_grab = tk.Toplevel.wait_window, tk.Toplevel.grab_set
    tk.Toplevel.wait_window = lambda self, *a: None
    tk.Toplevel.grab_set = lambda self: None

    print("=== 1. 进仓单：模拟逐格录入 ===")
    from app.ui.inbound_tab import InboundForm

    form = InboundForm(root, cid)
    g = form.grid
    edit_cell(g, 0, 0, "D2601")
    edit_cell(g, 0, 1, "涤纶四面弹")
    edit_cell(g, 0, 2, "藏青")
    edit_cell(g, 0, 3, "20")
    edit_cell(g, 0, 4, "1000")
    edit_cell(g, 1, 0, "D2602")
    edit_cell(g, 1, 1, "涤纶四面弹")
    edit_cell(g, 1, 2, "宝蓝")
    edit_cell(g, 1, 3, "10")
    edit_cell(g, 1, 4, "520")
    check("合计文案含 2 缸", "2 缸" in form.total.cget("text"), True)
    form.save()
    check("进仓保存成功", form.result, True)
    batches = {b["dye_lot"]: b for b in models.list_batches(cid)}
    check("缸号数", len(batches), 2)
    check("D2601 进仓米", batches["D2601"]["in_meters"], 1000.0)
    check("面料自动建档", batches["D2601"]["fabric"], "涤纶四面弹")

    print("\n=== 2. 非法输入：字母填进米数应被拒绝 ===")
    form2 = InboundForm(root, cid)
    g2 = form2.grid
    edit_cell(g2, 0, 0, "D9999")
    g2.begin_edit(0, 4)
    g2._editor.delete(0, "end")
    g2._editor.insert(0, "abc")
    g2._commit(move=None)
    check("非法米数未写入", g2.get_row(0)["meters"], "")
    g2.cancel_edit()
    form2.destroy()

    print("\n=== 3. 发货单：选缸号联动 + 工艺带价 ===")
    from app.ui.shipment_form import ShipmentForm

    sf = ShipmentForm(root, cid)
    sg = sf.grid
    edit_cell(sg, 0, 0, "D2601")
    row = sg.get_row(0)
    check("自动带出面料", row["fabric"], "涤纶四面弹")
    check("自动带出颜色", row["color"], "藏青")
    # 三段库存改版后这一列叫「可发」，还会写清是坯布还是成品
    check("自动带出可发", row["avail"], "未加工 20卷/1000米")
    check("自动填卷数=剩余", row["rolls"], 20)

    edit_cell(sg, 0, 4, "贴白膜")
    check("自动带出单价", sg.get_row(0)["unit_price"], 3.5)

    edit_cell(sg, 0, 5, "12")
    edit_cell(sg, 0, 6, "585")
    check("自动算金额", sg.get_row(0)["amount"], "2,047.50")

    print("\n=== 4. 通用价（面料留空）也能带出 ===")
    edit_cell(sg, 1, 0, "D2602")
    edit_cell(sg, 1, 4, "贴黑膜")
    check("通用价带出", sg.get_row(1)["unit_price"], 1.2)
    edit_cell(sg, 1, 5, "10")
    edit_cell(sg, 1, 6, "500")
    check("第二行金额", sg.get_row(1)["amount"], "600.00")

    sf.save()
    check("发货保存成功", sf.result, True)
    check("应收合计", services.statement(cid)["billed"], 2647.50)

    print("\n=== 5. 超发：点否不保存，点是放行 ===")
    answers["yes"] = False
    sf2 = ShipmentForm(root, cid)
    edit_cell(sf2.grid, 0, 0, "D2601")
    edit_cell(sf2.grid, 0, 4, "贴白膜")
    edit_cell(sf2.grid, 0, 5, "99")
    edit_cell(sf2.grid, 0, 6, "5000")
    sf2.save()
    check("点否 → 未保存", sf2.result, None)
    check("应收未变", services.statement(cid)["billed"], 2647.50)

    answers["yes"] = True
    sf2.save()
    check("点是 → 已保存", sf2.result, True)
    check("超发后应收增加", services.statement(cid)["billed"], 2647.50 + 5000 * 3.5)

    print("\n=== 6. 不存在的缸号应被拦下 ===")
    sf3 = ShipmentForm(root, cid)
    edit_cell(sf3.grid, 0, 0, "查无此缸")
    check("可发列提示", sf3.grid.get_row(0)["avail"], "缸号不存在")
    sf3.save()
    check("未保存", sf3.result, None)
    sf3.destroy()

    print("\n=== 7.「按剩余填满」按钮 ===")
    sf4 = ShipmentForm(root, cid)
    edit_cell(sf4.grid, 0, 0, "D2602")
    edit_cell(sf4.grid, 0, 5, "1")
    edit_cell(sf4.grid, 0, 6, "1")
    sf4.grid.tree.selection_set(sf4.grid.tree.get_children()[0])
    b = {x["dye_lot"]: x for x in models.list_batches(cid)}["D2602"]
    sf4.fill_left()
    check("填满卷数", sf4.grid.get_row(0)["rolls"], b["left_rolls"])
    check("填满米数", sf4.grid.get_row(0)["meters"], round(b["left_meters"], 2))
    sf4.destroy()

    print("\n=== 8. 码单解析（支持千分位、空行）===")
    from app.ui.inbound_tab import RollEditor
    re_ = RollEditor.__new__(RollEditor)
    tk.Toplevel.__init__(re_, root)
    re_.text = tk.Text(re_)
    re_.text.insert("1.0", "50.5\n49.5\n 50 \n\n1,000\n")
    check("解析码单", re_._parse(), [50.5, 49.5, 50.0, 1000.0])
    re_.destroy()

    print("\n=== 9. 日期输入的各种写法 ===")
    from datetime import date as _d

    from app.ui.widgets import parse_date
    y = _d.today().year
    check("2026-08-13", parse_date("2026-08-13"), "2026-08-13")
    check("2026/8/13", parse_date("2026/8/13"), "2026-08-13")
    check("20260813", parse_date("20260813"), "2026-08-13")
    check("0813（当年）", parse_date("0813"), f"{y}-08-13")
    check("空字符串", parse_date(""), None)
    try:
        parse_date("乱写")
        check("非法日期拦截", "未拦截", "应拦截")
    except ValueError:
        check("非法日期拦截", "已拦截", "已拦截")

    print("\n=== 10. 编辑已有发货单，金额正确回算 ===")
    sh = models.list_shipments(cid)[-1]
    before = services.statement(cid)["billed"]
    sf5 = ShipmentForm(root, cid, sh["id"])
    check("载入行数", len([r for r in sf5.grid.get_rows() if r.get("dye_lot")]), 2)
    edit_cell(sf5.grid, 0, 6, "580")
    sf5.save()
    check("改后应收减少 5×3.5", services.statement(cid)["billed"], before - 5 * 3.5)

    tk.Toplevel.wait_window, tk.Toplevel.grab_set = orig_wait, orig_grab
    root.destroy()

    print(f"\n{'=' * 40}\n通过 {PASS}，失败 {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
