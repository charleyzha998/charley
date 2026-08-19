"""数据层 + 业务层自测：跑一遍完整业务场景，断言关键计算。

用法：python selftest.py
会用独立的临时数据库，不影响正式数据。
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 在导入 db 之前改掉 DB_PATH
from app import db  # noqa: E402

_tmp = tempfile.mkdtemp(prefix="ferp_test_")
db.DATA_DIR = _tmp
db.DB_PATH = os.path.join(_tmp, "test.db")

from app import models, services  # noqa: E402

PASS, FAIL = 0, 0


def check(label, actual, expect):
    global PASS, FAIL
    ok = actual == expect
    if isinstance(expect, float) or isinstance(actual, float):
        ok = abs(float(actual) - float(expect)) < 0.005
    if ok:
        PASS += 1
        print(f"  OK   {label} = {actual}")
    else:
        FAIL += 1
        print(f"  FAIL {label} = {actual!r}, 期望 {expect!r}")


def main():
    print("=== 1. 建档 ===")
    cid = models.save_customer({"name": "宁波华丰针织", "contact": "张经理",
                                "phone": "13800138000", "opening_balance": 0,
                                "opening_date": "2026-01-01"})
    fid = models.get_or_create_fabric("涤纶四面弹")
    pid_dye = [p["id"] for p in models.list_processes() if p["name"] == "贴白膜"][0]
    check("客户已建", models.get_customer(cid)["name"], "宁波华丰针织")

    print("\n=== 2. 价格表 ===")
    models.save_price(cid, fid, pid_dye, 3.5, "2026-01-01")
    check("查到单价", services.lookup_price(cid, fid, pid_dye, "2026-08-01"), 3.5)

    print("\n=== 3. 进仓：缸号 D2601，20 卷 1000 米 ===")
    ib = services.save_inbound(cid, "2026-08-01", "8月首批", [
        {"dye_lot": "D2601", "fabric_id": fid, "color": "藏青",
         "rolls": 20, "meters": 1000},
    ])
    b = models.list_batches(cid)[0]
    check("单号格式", models.get_inbound(ib)[0]["doc_no"], "JC-20260801-001")
    check("状态", b["state"], "未加工")
    check("剩余卷", b["left_rolls"], 20)
    check("剩余米", b["left_meters"], 1000.0)
    item_id = b["item_id"]

    print("\n=== 4. 缸号重复应被拦截 ===")
    try:
        services.save_inbound(cid, "2026-08-02", "", [
            {"dye_lot": "D2601", "fabric_id": fid, "color": "黑", "rolls": 5, "meters": 250}])
        check("重复缸号拦截", "未拦截", "应拦截")
    except ValueError as e:
        check("重复缸号拦截", "已拦截", "已拦截")
        print(f"       提示：{e}")

    print("\n=== 5. 发货 1：12 卷 585 米 @3.5 ===")
    sid1, w = services.save_shipment(cid, "2026-08-05", "李师傅", "浙B12345", "", [
        {"inbound_item_id": item_id, "process_id": pid_dye,
         "rolls": 12, "meters": 585, "unit_price": 3.5}])
    head, items = models.get_shipment(sid1)
    check("发货单号", head["doc_no"], "FH-20260805-001")
    check("金额快照", items[0]["amount"], 2047.50)
    b = models.get_batch(item_id)
    check("状态", b["state"], "部分发货")
    check("剩余卷", b["left_rolls"], 8)
    check("剩余米", b["left_meters"], 415.0)
    check("未发完时不算缩率", b["shrink_pct"], None)

    print("\n=== 6. 发货 2：8 卷 390 米（发完，缩率 2.5%）===")
    sid2, w = services.save_shipment(cid, "2026-08-10", "李师傅", "浙B12345", "", [
        {"inbound_item_id": item_id, "process_id": pid_dye,
         "rolls": 8, "meters": 390, "unit_price": 3.5}])
    b = models.get_batch(item_id)
    check("卷数归零自动发完", b["state"], "已发完")
    check("剩余米（缩率差额）", b["left_meters"], 25.0)
    check("缩率%", b["shrink_pct"], 2.5)
    check("缩率 2.5% 不报警", services.is_shrink_abnormal(b["shrink_pct"]), False)
    check("缩率 12% 应报警", services.is_shrink_abnormal(12.0), True)
    check("缩率 -5% 应报警", services.is_shrink_abnormal(-5.0), True)

    print("\n=== 7. 超发应被拦截，force 可放行 ===")
    try:
        services.save_shipment(cid, "2026-08-11", "", "", "", [
            {"inbound_item_id": item_id, "process_id": pid_dye,
             "rolls": 5, "meters": 200, "unit_price": 3.5}])
        check("超发拦截", "未拦截", "应拦截")
    except services.OvershipError as e:
        check("超发拦截", "已拦截", "已拦截")
        print(f"       提示：{e}")

    print("\n=== 8. 收款 2000 ===")
    models.save_payment(cid, "2026-08-12", 2000, "转账", "TX20260812")
    st = services.statement(cid)
    check("本期应收", st["billed"], 3412.50)
    check("本期已收", st["paid"], 2000.0)
    check("期末欠款", st["closing"], 1412.50)
    check("对账明细行数", len(st["items"]), 2)
    check("合计卷数", st["total_rolls"], 20)
    check("合计米数", st["total_meters"], 975.0)

    print("\n=== 9. 改价格表，历史金额必须不变 ===")
    models.save_price(cid, fid, pid_dye, 4.0, "2026-08-15")
    check("新价生效", services.lookup_price(cid, fid, pid_dye, "2026-08-20"), 4.0)
    check("旧日期仍取旧价", services.lookup_price(cid, fid, pid_dye, "2026-08-10"), 3.5)
    check("历史单据金额不变", services.statement(cid)["billed"], 3412.50)

    print("\n=== 10. 期初欠款参与对账 ===")
    cid2 = models.save_customer({"name": "余姚新纺", "opening_balance": 5000,
                                 "opening_date": "2026-01-01"})
    st2 = services.statement(cid2)
    check("期初计入", st2["opening"], 5000.0)
    check("期末=期初", st2["closing"], 5000.0)

    print("\n=== 11. 日期区间：8/8~8/31，8/5 的单归入期初 ===")
    st3 = services.statement(cid, "2026-08-08", "2026-08-31")
    check("期初含 8/5 发货", st3["opening"], 2047.50)
    check("本期只含 8/10 那单", st3["billed"], 1365.00)
    check("本期收款", st3["paid"], 2000.00)
    check("期末欠款不变", st3["closing"], 1412.50)

    print("\n=== 12. 客户余额视图 ===")
    bal = models.get_customer_balance(cid)
    check("余额", bal["balance"], 1412.50)
    check("未发完批次数", bal["open_batches"], 0)

    print("\n=== 13. 在库统计（新缸号未发货）===")
    services.save_inbound(cid, "2026-08-12", "", [
        {"dye_lot": "D2602", "fabric_id": fid, "color": "宝蓝", "rolls": 10, "meters": 520}])
    bal = models.get_customer_balance(cid)
    check("未发完批次数", bal["open_batches"], 1)
    check("在库米数", bal["stock_meters"], 520.0)
    check("全局库存条数", len(services.global_stock()), 1)

    print("\n=== 14. 逐卷码单 ===")
    ib3 = services.save_inbound(cid, "2026-08-13", "", [
        {"dye_lot": "D2603", "fabric_id": fid, "color": "米白", "rolls": 3, "meters": 150,
         "rolls_detail": [50.5, 49.5, 50.0]}])
    _, its = models.get_inbound(ib3)
    rolls = models.list_rolls(its[0]["id"])
    check("码单卷数", len(rolls), 3)
    check("码单合计", round(sum(r["meters"] for r in rolls), 2), 150.0)

    print("\n=== 15. 有发货的进仓单不能删 ===")
    try:
        models.delete_inbound(ib)
        check("删除拦截", "未拦截", "应拦截")
    except ValueError:
        check("删除拦截", "已拦截", "已拦截")

    print("\n=== 16. 删发货单后库存回滚 ===")
    models.delete_shipment(sid2)
    b = models.get_batch(item_id)
    check("状态回到部分发货", b["state"], "部分发货")
    check("剩余卷恢复", b["left_rolls"], 8)
    check("应收减少", services.statement(cid)["billed"], 2047.50)

    print("\n=== 17. 老库升级：v1 的 NOT NULL 必须拆掉 ===")
    # v1 只有「进仓→发货」两段，每笔发货必然挂一缸，所以当时
    # inbound_item_id 写了 NOT NULL。v2 有了成品段和无缸号客户（逸峰这种
    # 做完直接发），发货可以不挂缸号 —— 老库不改的话这种发货一条都存不进去，
    # 报 NOT NULL constraint failed，应收凭空少掉。真实数据上踩过这个坑。
    import shutil
    import sqlite3 as _s3
    v1dir = os.path.join(_tmp, "v1")
    os.makedirs(v1dir, exist_ok=True)
    v1 = os.path.join(v1dir, "old.db")
    # 先把 WAL 里的东西刷进主文件，否则拷出来的是个空壳
    db.get_conn().execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.get_conn().commit()
    shutil.copy(db.DB_PATH, v1)
    c0 = _s3.connect(v1)
    n0 = c0.execute("SELECT COUNT(*) FROM shipment_item").fetchone()[0]
    a0 = c0.execute("SELECT IFNULL(SUM(amount),0) FROM shipment_item").fetchone()[0]
    # 造回 v1 的样子：重建成 NOT NULL 的表 + 把版本号降回 1
    c0.executescript("""
        PRAGMA foreign_keys=OFF;
        DROP VIEW IF EXISTS v_batch_stock;
        DROP VIEW IF EXISTS v_finished_stock;
        DROP VIEW IF EXISTS v_customer_balance;
        CREATE TABLE si_old (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_id INTEGER NOT NULL,
            inbound_item_id INTEGER NOT NULL,
            process_id INTEGER, rolls INTEGER NOT NULL DEFAULT 0,
            meters REAL NOT NULL DEFAULT 0, unit_price REAL NOT NULL DEFAULT 0,
            amount REAL NOT NULL DEFAULT 0, note TEXT,
            production_id INTEGER, fabric_id INTEGER, color TEXT, weight REAL);
        INSERT INTO si_old(id,shipment_id,inbound_item_id,process_id,rolls,meters,
                           unit_price,amount,note,production_id,fabric_id,color,weight)
            SELECT id,shipment_id,IFNULL(inbound_item_id,0),process_id,rolls,meters,
                   unit_price,amount,note,production_id,fabric_id,color,weight
            FROM shipment_item;
        DROP TABLE shipment_item;
        ALTER TABLE si_old RENAME TO shipment_item;
        UPDATE schema_version SET version=1;""")
    c0.commit()
    ddl = c0.execute("SELECT sql FROM sqlite_master WHERE name='shipment_item'").fetchone()[0]
    check("造出来的老库确实是 NOT NULL",
          "NOT NULL" in ddl.split("inbound_item_id")[1].split(",")[0], True)
    c0.close()

    old_dir, old_path = db.DATA_DIR, db.DB_PATH
    db.DATA_DIR, db.DB_PATH = v1dir, v1
    db._conn = db._local = None
    c = db.get_conn()             # 触发迁移
    ddl2 = c.execute("SELECT sql FROM sqlite_master WHERE name='shipment_item'"
                     ).fetchone()["sql"]
    check("升级后可以不挂缸号",
          "NOT NULL" in ddl2.split("inbound_item_id")[1].split(",")[0], False)
    check("老单据一条没丢",
          c.execute("SELECT COUNT(*) c FROM shipment_item").fetchone()["c"], n0)
    check("金额分毫不差",
          round(c.execute("SELECT IFNULL(SUM(amount),0) a FROM shipment_item"
                          ).fetchone()["a"], 2), round(a0, 2))
    check("视图重建好了",
          len([r["name"] for r in c.execute(
              "SELECT name FROM sqlite_master WHERE type='view'")]), 3)
    # 真正的验收：往老库里存一笔不挂缸号的发货（逸峰那种）
    cid9 = models.save_customer({"name": "直发客户", "opening_balance": 0,
                                 "use_dye_lot": 0})
    f9 = models.get_or_create_fabric("直发布")
    sid9, _ = services.save_shipment(cid9, "2026-08-14", "", "", "", [
        {"fabric_id": f9, "rolls": 3, "meters": 300, "unit_price": 2}])
    check("老库升级后能存无缸号发货", bool(sid9), True)
    check("金额算对", services.statement(cid9)["billed"], 600.0)

    db.DATA_DIR, db.DB_PATH = old_dir, old_path
    db._conn = db._local = None
    db.get_conn()

    print("\n=== 18. 编辑进仓单不得删除有加工记录的缸号（回归测试）===")
    cid18 = models.save_customer({"name": "回归测试客户", "opening_balance": 0,
                                  "use_dye_lot": 1})
    ib18 = services.save_inbound(cid18, "2026-08-15", "", [
        {"dye_lot": "T001", "fabric_id": fid, "color": "黑",
         "rolls": 10, "meters": 1000},
        {"dye_lot": "T002", "fabric_id": fid, "color": "白",
         "rolls": 5, "meters": 500},
    ])
    _h, _items = models.get_inbound(ib18)
    services.save_production({"customer_id": cid18, "inbound_item_id": _items[0]["id"],
                              "done_date": "2026-08-15", "process_id": pid_dye,
                              "fabric_id": fid, "color": "黑", "rolls": 10,
                              "meters": 1000, "weight": None, "note": ""})
    # 编辑：两个缸号都保留，只改备注 —— 不能丢数据
    _h, _items = models.get_inbound(ib18)
    keep = [{"id": it["id"], "dye_lot": it["dye_lot"], "fabric_id": it["fabric_id"],
             "color": it["color"], "rolls": it["rolls"], "meters": it["meters"],
             "note": ""} for it in _items]
    services.save_inbound(cid18, "2026-08-15", "改备注", keep, ib18)
    lots_after = sorted(r["dye_lot"] for r in models.get_inbound(ib18)[1])
    check("编辑后两个缸号都在", lots_after, ["T001", "T002"])
    prod_n = db.get_conn().execute(
        "SELECT COUNT(*) c FROM production p JOIN inbound_item ii "
        "ON ii.id=p.inbound_item_id WHERE ii.inbound_id=? AND p.deleted=0",
        (ib18,)).fetchone()["c"]
    check("编辑后加工记录还在", prod_n, 1)
    # 编辑：删掉有加工记录的 T001 —— 应被拒绝
    _h, _items = models.get_inbound(ib18)
    blocked = False
    try:
        services.save_inbound(cid18, "2026-08-15", "", [
            {"id": it["id"], "dye_lot": it["dye_lot"], "fabric_id": it["fabric_id"],
             "color": it["color"], "rolls": it["rolls"], "meters": it["meters"],
             "note": ""} for it in _items if it["dye_lot"] != "T001"], ib18)
    except ValueError:
        blocked = True
    check("删除有加工记录的缸号会被拦截", blocked, True)
    # 编辑：删掉没有任何记录的 T002 —— 应允许
    _h, _items = models.get_inbound(ib18)
    services.save_inbound(cid18, "2026-08-15", "", [
        {"id": it["id"], "dye_lot": it["dye_lot"], "fabric_id": it["fabric_id"],
         "color": it["color"], "rolls": it["rolls"], "meters": it["meters"],
         "note": ""} for it in _items if it["dye_lot"] != "T002"], ib18)
    check("删除无记录缸号被允许",
          [r["dye_lot"] for r in models.get_inbound(ib18)[1]], ["T001"])

    print(f"\n{'=' * 40}\n通过 {PASS}，失败 {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
