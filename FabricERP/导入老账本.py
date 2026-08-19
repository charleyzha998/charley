# -*- coding: utf-8 -*-
"""把老账本导进真数据库（命令行版，跟软件里「导入老账本」按钮做的事一样）。

用法：
    python 导入老账本.py                      # 用默认的账本文件夹
    python 导入老账本.py "D:\\某个文件夹"       # 指定文件夹
    python 导入老账本.py --dry                # 只看会导入什么，不写库

导入前自动备份，出问题照备份还原就行。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEFAULT_DIR = r"H:\360MoveData\Users\Z\Desktop\客户"


def find(folder, *keys):
    """文件名里同时含这几个词的那个文件。"""
    for fn in sorted(os.listdir(folder)):
        if fn.startswith("~$"):          # Excel 开着时的临时文件
            continue
        if os.path.splitext(fn)[1].lower() not in (".xls", ".xlsx"):
            continue
        if all(k in fn for k in keys):
            return os.path.join(folder, fn)
    return None


def build(folder):
    """解析出各家的数据。跟 legacy_window._parse_job 一致。"""
    from app import legacy_import as LI

    plans = []

    f_in, f_st = find(folder, "鹏川", "入库"), find(folder, "鹏川", "对账")
    if f_in and f_st:
        a = LI.PengchuanInboundRule().parse(LI.read_sheets(f_in))
        b = LI.PengchuanStatementRule().parse(LI.read_sheets(f_st))
        LI.pc_link_ship(a, b)            # 发货挂到成品上，库存才扣得下来
        plans.append({"customer": "鹏川纺织", "parts": [a, b]})
    else:
        print("!! 没找到鹏川的入库明细或对账明细")

    f = find(folder, "逸峰")
    if f:
        plans.append({"customer": "逸峰纺织",
                      "parts": [LI.YifengRule().parse(LI.read_sheets(f))]})
    else:
        print("!! 没找到逸峰的表")

    f_in, f_sh = find(folder, "龚松权", "入库"), find(folder, "龚松权", "发货")
    if f_in and f_sh:
        plans.append({"customer": "龚松权",
                      "parts": [LI.gs_parse_pair(LI.read_sheets(f_in),
                                                 LI.read_sheets(f_sh))]})
    else:
        print("!! 没找到龚松权的入库表或发货对账单")

    return plans


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    folder = args[0] if args else DEFAULT_DIR
    if not os.path.isdir(folder):
        print("找不到文件夹：%s" % folder)
        return 1

    from app import db, legacy_commit as LC

    db.get_conn()
    print("账本文件夹：%s" % folder)
    print("数据库：%s\n" % db.DB_PATH)

    plans = build(folder)
    if not plans:
        print("没认出任何账本，什么都没做。")
        return 1

    print("解析结果：")
    for p in plans:
        for i, part in enumerate(p["parts"]):
            got = "　".join("%s %d" % (k, v)
                            for k, v in part.stats.items() if v)
            print("  %s（第%d份）：%s" % (p["customer"], i + 1, got or "没有数据"))
            for m in part.report.errors:
                print("     错误：%s" % m)

    if dry:
        print("\n--dry：只解析，没有写库。")
        return 0

    print("\n导入前备份：%s" % LC.backup_db())
    warns = []
    for p in plans:
        # 鹏川分两份导：加工在入库明细里、发货在对账明细里，
        # 靠同一个 pids 把发货挂到成品上。
        pids = {}
        for part in p["parts"]:
            rep = LC.commit(part, p["customer"], prod_ids=pids)
            print("  %s → %s" % (p["customer"], rep.summary))
            warns.extend(rep.warnings)
            # 跳过的必须看得见原因 —— 一整类被跳掉（比如所有发货）就等于
            # 应收全丢了，只报个数字根本发现不了
            for what, why in rep.skipped:
                warns.append("跳过 %s —— %s" % (what, why))
            if rep.skipped:
                seen = {}
                for what, why in rep.skipped:
                    seen.setdefault(str(why), 0)
                    seen[str(why)] += 1
                for why, n in sorted(seen.items(), key=lambda x: -x[1]):
                    print("      跳过 %d 条，原因：%s" % (n, why))

    print("\n导入完成。%d 条要留意的（已写进单据备注）。" % len(warns))

    from app import models
    print("\n现在库里：")
    for r in models.list_customers():
        print("  %-10s 应收 %12.2f  已收 %12.2f  结欠 %12.2f  在库 %s 缸 %s 米"
              % (r["customer"], r["billed"] or 0, r["paid"] or 0,
                 r["balance"] or 0, r["open_batches"] or 0,
                 round(r["stock_meters"] or 0)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
