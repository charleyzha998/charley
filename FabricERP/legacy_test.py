# -*- coding: utf-8 -*-
"""老账本导入测试。

两部分：
  · 构造小表测各个零件（不依赖真实账本，任何机器上都能跑）
  · 加 --real 参数时，拿桌面上的真实账本跑一遍全流程，并且用账本自己写的
    合计行核对结果 —— 这是最硬的验证，分组错一行金额立刻对不上。
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TMP = tempfile.mkdtemp(prefix="erp_legacy_test_")
from app import db                                    # noqa: E402

db.DATA_DIR = TMP
db.DB_PATH = os.path.join(TMP, "t.db")

from app import legacy_commit as C                     # noqa: E402
from app import legacy_import as L                     # noqa: E402
from app import models                                 # noqa: E402

PASS = FAIL = 0


def ck(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  OK   %s" % name)
    else:
        FAIL += 1
        print("  FAIL %s   %s" % (name, extra))


def sheet(name, rows):
    """用 list of list 造一张表，1-based 索引由 Sheet 自己管。"""
    return L.Sheet(name, [list(r) for r in rows])


def test_helpers():
    print("\n[1] 洗数据的零件")
    ck("缸号补零：数字", L.gs_lot(3778.0) == "3778")
    ck("缸号补零：三位数", L.gs_lot(58.0) == "0058", L.gs_lot(58.0))
    ck("缸号补零：文本保持", L.gs_lot("0264") == "0264")
    ck("缸号：非数字原样", L.gs_lot("花艺宝印花") == "花艺宝印花")
    ck("批次号带月日", L.gs_batch_no("4818", "2026-07-02") == "4818@0702",
       L.gs_batch_no("4818", "2026-07-02"))

    ck("表名取月：3月份", L.sheet_month("3月份") == 3)
    ck("表名取月：2026年4月", L.sheet_month("2026年4月") == 4)
    ck("表名取月：带括号", L.sheet_month("2026年5月)") == 5)
    ck("表名取月：认不出给默认", L.sheet_month("单价", 9) == 9)

    m, raw = L.parse_meters("10000(实际米数：9800米）")
    ck("括号里的实际米数优先", m == 9800, m)
    ck("原文留着备查", "10000" in raw, raw)
    ck("大卷装不当品名", L.split_product("杂布（大卷装）")[0] == "杂布",
       L.split_product("杂布（大卷装）"))
    p, proc, _ = L.split_product("厚布杂布（贴60克黑针织）")
    ck("括号里的工艺拆出来", (p, proc) == ("厚布杂布", "贴60克黑针织"), (p, proc))
    ck("合计行认得出", L.is_sum_text("合计：") and L.is_sum_text("总计"))
    ck("普通品名不算合计", not L.is_sum_text("厚布杂布"))


def test_gongsongquan():
    print("\n[2] 龚松权：缸号重复用，靠日期认批次")
    # 4818 缸来过两次，米数不同 —— 这是真实账本里的情况
    ins = sheet("2022-2026", [
        ["日期", "缸号", "面料名称", "颜色", "进仓卷数", "进仓米数", "库存",
         "发完", "备注", ""],
        ["2026-03-28", 4818.0, "T400威龙格", "523绿卡", 12, 1000, 0, "✅", "", ""],
        ["2026-07-02", 4818.0, "T400威龙格", "523绿卡", 12, 1933, 72, "", "", ""],
        ["2026-05-10", "0605", "新叉叉格", "316军绿", 9, 1735, 1735, "", "", ""],
    ])
    shp = sheet("7月份", [
        ["发货日期", "缸号", "面料名称", "颜色", "发货卷数", "发货米数",
         "加工方式", "单价", "金额", "打款日期", "客户打款", "累计结欠金额"],
        ["2026-07-10", 4818.0, "T400威龙格", "523绿卡", 11, 1861, "白膜", 0.9,
         1674.9, "", "", ""],
        [None, None, None, "总计", 11, 1861, None, None, 1674.9, None, 0, 0],
    ])

    ship = L.GongsongquanShipmentRule().parse([shp], 2026)
    ck("发货读到 1 笔", len(ship.shipments) == 1, ship.stats)
    ck("总计行不当发货", ship.shipments[0]["meters"] == 1861)

    raw = L.GongsongquanInboundRule().read_batches([ins])
    sent, orphan = L.gs_allocate(raw, ship)
    ck("发货配到 7月那批（不是3月那批）",
       sent.get(("4818", "2026-07-02")) == 1861, sent)
    ck("没有配不上的", not orphan, orphan)
    ck("发货缸号改写成批次号", ship.shipments[0]["dye_lot"] == "4818@0702",
       ship.shipments[0]["dye_lot"])

    res = L.gs_parse_pair([ins], [shp], 2026)
    lots = {x["dye_lot"]: x for x in res.inbounds}
    ck("3月那批发完了，不导", "4818@0328" not in lots, list(lots))
    ck("7月那批照原样导", lots["4818@0702"]["meters"] == 1933,
       lots.get("4818@0702"))
    ck("4月后进的货不动库存列", lots["0605@0510"]["meters"] == 1735)


def test_footer_traps():
    print("\n[3] 表尾陷阱：别把汇总行当成真数据")
    # 真实账本里 4月 r77 既是发货、又在右边写了「3月底累计结欠金额」
    shp = sheet("4月份", [
        ["缸号", "发货日期", "面料名称", "颜色", "发货卷数", "发货米数",
         "加工方式", "单价", "金额", "打款日期", "客户打款", "累计结欠金额", ""],
        ["2869", "2026-04-30", "150D消光高弹", "911棕色", 2, 342, "白膜", 0.9,
         307.8, "2026-04-28", 30000, 316094.23, "3月底累计结欠金额"],
        [None, None, None, "总计", 2, 342, None, None, 307.8, None, 30000, 0, ""],
    ])
    res = L.GongsongquanShipmentRule().parse([shp], 2026)
    ck("这行的发货没被误杀", len(res.shipments) == 1, res.stats)
    ck("米数是 342", res.shipments[0]["meters"] == 342)
    ck("期初欠款认出来了", res.opening_debt == 316094.23, res.opening_debt)
    ck("打款只算一笔（总打款不重复）", len(res.payments) == 1, res.payments)
    ck("打款是 30000", res.payments[0]["amount"] == 30000)

    # 账本表尾手打的总计跟明细不一致 —— 要提醒，但按明细导
    shp2 = sheet("5月份", [
        ["缸号", "发货日期", "面料名称", "颜色", "发货卷数", "发货米数",
         "加工方式", "单价", "金额", "打款日期", "客户打款", "累计结欠金额"],
        ["1001", "2026-05-06", "杂布", "黑", 5, 1000, "白膜", 1.0, 1000,
         "", "", ""],
        [None, None, None, "总计", 5, 9999, None, None, 1000, None, 0, 0],
    ])
    res2 = L.GongsongquanShipmentRule().parse([shp2], 2026)
    ck("明细为准（1000 米）",
       sum(x["meters"] for x in res2.shipments) == 1000)
    ck("总计对不上要提醒",
       any("总计" in w and "9999" in w for w in res2.report.warnings),
       res2.report.warnings)


def test_yifeng():
    print("\n[4] 逸峰：三版表头，列序会颠倒")
    # C 版：卷装米数在米数前面
    s = sheet("2026年6月", [
        ["客户：逸峰", "", "", "", "", "", "", "", "", ""],
        ["日期", "品名", "加工要求", "卷装米数", "米数", "单价", "金额",
         "打款日期", "打款金额", "结欠"],
        ["2026-06-03", "杂布", "PE膜", 3000, 2500, 0.9, 2250, "", "", ""],
        ["4/31", "杂布", "防水", "/", 4179, 0.3, 1253.7, "", "", ""],
        [None, None, None, None, 6679, "合计", 3503.7, None, 50000, 0],
    ])
    res = L.YifengRule().parse([s], 2026)
    ck("按标题找列，不按列号", len(res.shipments) == 2, res.stats)
    ck("计费用「米数」不是「卷装米数」",
       sum(x["meters"] for x in res.shipments) == 6679,
       sum(x["meters"] for x in res.shipments))
    ck("卷装米数写进备注", "卷装米数" in res.shipments[0]["note"],
       res.shipments[0]["note"])
    ck("写错的日期 4/31 不丢货",
       any(x["meters"] == 4179 for x in res.shipments))
    ck("写错日期要提醒",
       any("4/31" in w for w in res.report.warnings), res.report.warnings)
    ck("表尾总打款不算真打款", not res.payments, res.payments)


def test_commit():
    print("\n[5] 写进数据库")
    db.init_schema(db.get_conn())
    res = L.ParseResult("测试客户")
    res.inbounds.append({"in_date": "2026-03-07", "dye_lot": "A001",
                         "fabric": "春亚纺", "color": "黑", "rolls": 10,
                         "meters": 1000, "sheet": "3月份", "row": 2})
    res.productions.append({"done_date": "2026-03-08", "dye_lot": "A001",
                            "fabric": "春亚纺", "color": "黑", "process": "白膜",
                            "rolls": 10, "meters": 1000, "key": "P0",
                            "sheet": "3月份", "row": 2})
    res.shipments.append({"ship_date": "2026-03-14", "fabric": "春亚纺",
                          "process": "白膜", "rolls": 10, "meters": 990,
                          "unit_price": 1.9, "prod_key": "P0",
                          "sheet": "3月份", "row": 2})
    res.payments.append({"pay_date": "2026-03-20", "amount": 1000,
                         "method": "转账", "sheet": "3月份", "row": 2})
    res.prices.append({"fabric": "春亚纺", "process": "白膜", "unit_price": 1.9,
                       "sheet": "单价", "row": 2})
    rep = C.commit(res, "测试客户")
    ck("进仓进去了", rep.counts.get("进仓") == 1, rep.counts)
    ck("加工进去了", rep.counts.get("加工") == 1, rep.counts)
    ck("发货进去了", rep.counts.get("发货") == 1, rep.counts)
    ck("收款进去了", rep.counts.get("收款") == 1, rep.counts)
    ck("没有跳过的", not rep.skipped, rep.skipped)

    cid = [c["customer_id"] for c in models.list_customers()
           if c["customer"] == "测试客户"][0]
    b = models.list_batches(cid)[0]
    ck("单据带来源行号", "3月份第2行" in (b["note"] or ""), b["note"])
    ck("只挂成品的发货也扣了坯布库存",
       abs(b["out_meters"] - 990) < 0.01, b["out_meters"])
    bal = models.get_customer_balance(cid)
    ck("应收 1881.00", abs(bal["billed"] - 1881.0) < 0.01, bal["billed"])
    ck("已收 1000", abs(bal["paid"] - 1000) < 0.01, bal["paid"])

    # 期初欠款：客户已存在时也要补上
    res2 = L.ParseResult("测试客户")
    res2.opening_debt = 5000
    res2.opening_note = "[4月份] 第77行"
    rep2 = C.commit(res2, "测试客户")
    ck("期初欠款补到已有客户上", rep2.counts.get("期初欠款") == 1, rep2.counts)
    ck("期初进了余额",
       abs(models.get_customer_balance(cid)["balance"] - (1881 - 1000 + 5000)) < 0.01,
       models.get_customer_balance(cid)["balance"])


def test_real():
    """真实账本冒烟 + 用账本自己的合计核对。"""
    print("\n[6] 真实账本（--real）")
    try:
        import ledger_paths
        d = ledger_paths.ledger_dir()
    except Exception as e:
        print("  跳过：找不到账本目录（%s）" % e)
        return

    def f(*keys):
        for n in os.listdir(d):
            if all(k in n for k in keys):
                return os.path.join(d, n)
        return None

    # 鹏川：六个月的米数和金额要跟账本合计对上
    p = f("鹏川", "对账")
    if p:
        r = L.PengchuanStatementRule().parse(L.read_sheets(p), 2026)
        tot = sum(x["meters"] for x in r.shipments)
        amt = sum(x["meters"] * (x["unit_price"] or 0) for x in r.shipments)
        ck("鹏川发货 2093545 米", abs(tot - 2093545) < 1, tot)
        ck("鹏川金额 2281522.70 元", abs(amt - 2281522.70) < 0.05, amt)
        ck("鹏川收款 10 笔", len(r.payments) == 10, len(r.payments))

    p = f("逸峰")
    if p:
        r = L.YifengRule().parse(L.read_sheets(p), 2026)
        by = {}
        for x in r.shipments:
            by[x["sheet"]] = by.get(x["sheet"], 0) + x["meters"]
        ck("逸峰 2026年3月 155725 米", abs(by.get("2026年3月", 0) - 155725) < 1,
           by.get("2026年3月"))
        ck("逸峰 2026年7月 122635 米", abs(by.get("2026年7月", 0) - 122635) < 1,
           by.get("2026年7月"))
        ck("逸峰没有读不出的错误", not r.report.errors, r.report.errors)

    pin, psh = f("龚松权", "入库"), f("龚松权", "发货")
    if pin and psh:
        r = L.gs_parse_pair(L.read_sheets(pin), L.read_sheets(psh), 2026)
        by = {}
        for x in r.shipments:
            by[x["sheet"]] = by.get(x["sheet"], 0) + x["meters"] * (x["unit_price"] or 0)
        ck("龚松权 5月 103826.55 元", abs(by.get("5月份", 0) - 103826.55) < 0.05,
           by.get("5月份"))
        ck("龚松权 7月 129157.40 元", abs(by.get("7月份", 0) - 129157.40) < 0.05,
           by.get("7月份"))
        ck("龚松权期初欠款 316094.23", r.opening_debt == 316094.23, r.opening_debt)


def main():
    print("=" * 58)
    print("老账本导入测试")
    print("=" * 58)
    test_helpers()
    test_gongsongquan()
    test_footer_traps()
    test_yifeng()
    test_commit()
    if "--real" in sys.argv:
        test_real()
    print("\n" + "=" * 58)
    print("通过 %d，失败 %d" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        db.close_conn()
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(code)
