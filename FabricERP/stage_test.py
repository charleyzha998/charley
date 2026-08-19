"""三段库存（坯布 → 成品 → 已发）端到端测试。"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TMP = tempfile.mkdtemp(prefix="fabric_stage_")
from app import db  # noqa: E402

db.DATA_DIR = TMP
db.DB_PATH = os.path.join(TMP, "t.db")

from app import models, services  # noqa: E402

PASS = FAIL = 0


def ck(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}  {extra}")


def show(b, tag):
    print(f"    {tag}: 坯布 {b['greige_rolls']}卷/{b['greige_meters']}米 | "
          f"成品待发 {b['fin_rolls']}卷/{b['fin_meters']}米 | "
          f"已发 {b['out_rolls']}卷/{b['out_meters']}米 | {b['state']}")


def main():
    print("=" * 56)
    print("三段库存测试")
    print("=" * 56)

    print("\n[1] 建客户与基础资料")
    cid = models.save_customer({"name": "龚松权", "opening_balance": 0,
                                "use_dye_lot": 1})
    yf = models.save_customer({"name": "逸峰纺织", "opening_balance": 0,
                               "use_dye_lot": 0})
    ck("按缸号客户", models.get_customer(cid)["use_dye_lot"] == 1)
    ck("无缸号客户", models.get_customer(yf)["use_dye_lot"] == 0)

    fid = models.get_or_create_fabric("春亚纺")
    zab = models.get_or_create_fabric("杂布")
    procs = {p["name"]: p["id"] for p in models.list_processes()}
    ck("工艺预置含白膜", "白膜" in procs, list(procs)[:5])
    ck("工艺预置含 PE膜", "PE膜" in procs)

    print("\n[2] 进仓 1700 米 / 10 卷")
    services.save_inbound(cid, "2026-07-01", "", [
        {"dye_lot": "T1001", "fabric_id": fid, "color": "藏青",
         "rolls": 10, "meters": 1700}])
    b = models.list_batches(cid)[0]
    iid = b["item_id"]
    show(b, "①进仓")
    ck("坯布 10 卷 1700 米", b["greige_rolls"] == 10 and b["greige_meters"] == 1700)
    ck("成品 0", b["fin_meters"] == 0)
    ck("状态未加工", b["state"] == "未加工", b["state"])

    print("\n[3] 只加工了 500 米 / 3 卷，还没发")
    services.save_production({
        "customer_id": cid, "inbound_item_id": iid, "done_date": "2026-07-05",
        "process_id": procs["白膜"], "rolls": 3, "meters": 500})
    b = models.get_batch(iid)
    show(b, "②加工")
    ck("坯布剩 7 卷 1200 米", b["greige_rolls"] == 7 and b["greige_meters"] == 1200)
    ck("成品待发 3 卷 500 米", b["fin_rolls"] == 3 and b["fin_meters"] == 500)
    ck("已发仍为 0", b["out_meters"] == 0)
    ck("状态待发货", b["state"] == "待发货", b["state"])

    bal = models.get_customer_balance(cid)
    ck("客户成品待发 500", abs(bal["fin_meters"] - 500) < 0.01, bal["fin_meters"])

    print("\n[4] 成品发货 3 卷 490 米（缩了 10 米）")
    prod = models.list_productions_of_batch(iid)[0]
    ck("成品记录带出缸号", prod["dye_lot"] == "T1001", prod["dye_lot"])
    ck("成品记录带出面料", prod["fabric"] == "春亚纺", prod["fabric"])
    ck("成品状态待发货", prod["state"] == "待发货", prod["state"])

    sid, w = services.save_shipment(cid, "2026-07-08", "", "", "", [
        {"inbound_item_id": iid, "production_id": prod["prod_id"],
         "process_id": procs["白膜"], "rolls": 3, "meters": 490, "unit_price": 1.2}])
    ck("发货无超发警告", not w, w)
    b = models.get_batch(iid)
    show(b, "③发货")
    ck("坯布不受影响 7 卷 1200 米", b["greige_rolls"] == 7 and b["greige_meters"] == 1200)
    ck("成品待发只剩 0 卷 10 米", b["fin_rolls"] == 0 and b["fin_meters"] == 10)
    ck("已发 3 卷 490 米", b["out_rolls"] == 3 and b["out_meters"] == 490)
    ck("状态部分发货", b["state"] == "部分发货", b["state"])
    bal = models.get_customer_balance(cid)
    # 3 卷全发掉了，剩的 10 米是缩率零头，不算压在厂里的成品
    ck("客户成品待发归 0（10 米是缩率）", abs(bal["fin_meters"]) < 0.01, bal["fin_meters"])
    ck("应收 588.00", abs(bal["billed"] - 588.0) < 0.01, bal["billed"])

    print("\n[5] 剩下的 7 卷 1180 米也加工完")
    pid2 = services.save_production({
        "customer_id": cid, "inbound_item_id": iid, "done_date": "2026-07-12",
        "process_id": procs["白膜"], "rolls": 7, "meters": 1180})[0]
    b = models.get_batch(iid)
    show(b, "④加工")
    ck("坯布清空（剩 0 卷 20 米零头）",
       b["greige_rolls"] == 0 and abs(b["greige_meters"] - 20) < 0.01,
       (b["greige_rolls"], b["greige_meters"]))
    ck("成品待发 7 卷 1190 米", b["fin_rolls"] == 7 and abs(b["fin_meters"] - 1190) < 0.01,
       (b["fin_rolls"], b["fin_meters"]))
    ck("状态仍是部分发货", b["state"] == "部分发货", b["state"])

    print("\n[6] 坯布不够时要警告")
    try:
        services.save_production({
            "customer_id": cid, "inbound_item_id": iid, "done_date": "2026-07-13",
            "process_id": procs["白膜"], "rolls": 5, "meters": 800})
        ck("超量加工应被拦截", False)
    except services.OverproduceError as e:
        ck("超量加工被拦截", True)
        ck("提示坯布只剩多少", "只剩" in str(e), str(e))
    _, w = services.save_production({
        "customer_id": cid, "inbound_item_id": iid, "done_date": "2026-07-13",
        "process_id": procs["白膜"], "rolls": 0, "meters": 50}, force=True)
    ck("force 可强制录入", bool(w), w)
    models.delete_production(models.list_productions_of_batch(iid)[-1]["prod_id"])
    ck("删掉刚才那条后成品回到 1190",
       abs(models.get_batch(iid)["fin_meters"] - 1190) < 0.01,
       models.get_batch(iid)["fin_meters"])

    print("\n[7] 第二张发货单：把剩下的 7 卷 1175 米发掉")
    p2 = [p for p in models.list_productions_of_batch(iid) if p["prod_id"] == pid2][0]
    services.save_shipment(cid, "2026-07-15", "", "", "", [
        {"inbound_item_id": iid, "production_id": p2["prod_id"],
         "process_id": procs["白膜"], "rolls": 7, "meters": 1175, "unit_price": 1.2}])
    b = models.get_batch(iid)
    show(b, "⑤发完")
    ck("已发 10 卷 1665 米", b["out_rolls"] == 10 and abs(b["out_meters"] - 1665) < 0.01,
       (b["out_rolls"], b["out_meters"]))
    ck("状态自动置已发完", b["state"] == "已发完", b["state"])
    ck("缩率 2.06%", abs(b["shrink_pct"] - 2.06) < 0.01, b["shrink_pct"])
    ck("一缸牵扯两张发货单", len(models.list_shipments(cid)) == 2)

    bal = models.get_customer_balance(cid)
    ck("发完后成品待发为 0", abs(bal["fin_meters"]) < 0.01, bal["fin_meters"])
    ck("发完后不算在库", bal["open_batches"] == 0, bal["open_batches"])
    ck("应收 2 张单合计 1998.00", abs(bal["billed"] - 1998.0) < 0.01, bal["billed"])

    print("\n[8] 成品超发要拦截")
    services.save_inbound(cid, "2026-07-20", "", [
        {"dye_lot": "T1002", "fabric_id": fid, "color": "黑", "rolls": 5, "meters": 800}])
    i2 = [x for x in models.list_batches(cid) if x["dye_lot"] == "T1002"][0]["item_id"]
    p3, _ = services.save_production({
        "customer_id": cid, "inbound_item_id": i2, "done_date": "2026-07-22",
        "process_id": procs["复合"], "rolls": 2, "meters": 300})
    try:
        services.save_shipment(cid, "2026-07-23", "", "", "", [
            {"inbound_item_id": i2, "production_id": p3,
             "process_id": procs["复合"], "rolls": 4, "meters": 600, "unit_price": 1}])
        ck("超过成品量应拦截", False)
    except services.OvershipError as e:
        ck("超过成品量被拦截", True)
        ck("提示按成品算", "成品" in str(e), str(e))

    print("\n[9] 无缸号客户：不进仓、不加工，直接发")
    sid3, w = services.save_shipment(yf, "2026-07-10", "", "", "", [
        {"fabric_id": zab, "color": "本白", "process_id": procs["PE膜"],
         "rolls": 0, "meters": 4521, "unit_price": 0.82, "note": "杂布"}])
    ck("无缸号发货不报超发", not w, w)
    head, its = models.get_shipment(sid3)
    ck("明细缸号为空", its[0]["dye_lot"] == "", its[0]["dye_lot"])
    ck("明细面料取自己填的", its[0]["fabric"] == "杂布", its[0]["fabric"])
    ck("明细颜色取自己填的", its[0]["color"] == "本白", its[0]["color"])
    ck("金额 3707.22", abs(its[0]["amount"] - 3707.22) < 0.01, its[0]["amount"])

    st = services.statement(yf)
    ck("无缸号客户对账应收 3707.22", abs(st["billed"] - 3707.22) < 0.01, st["billed"])
    ck("对账明细能出来", len(st["items"]) == 1)
    ck("对账明细面料正确", st["items"][0]["fabric"] == "杂布", st["items"][0]["fabric"])
    ck("无缸号客户无库存", models.get_customer_balance(yf)["open_batches"] == 0)

    print("\n[10] 没有卷数的缸：按米数留零头判发完")
    services.save_inbound(cid, "2026-08-01", "", [
        {"dye_lot": "T1003", "fabric_id": fid, "color": "红", "rolls": 0, "meters": 1000}])
    i3 = [x for x in models.list_batches(cid) if x["dye_lot"] == "T1003"][0]["item_id"]
    p4, _ = services.save_production({
        "customer_id": cid, "inbound_item_id": i3, "done_date": "2026-08-02",
        "process_id": procs["白膜"], "rolls": 0, "meters": 990})
    services.save_shipment(cid, "2026-08-03", "", "", "", [
        {"inbound_item_id": i3, "production_id": p4, "process_id": procs["白膜"],
         "rolls": 0, "meters": 985, "unit_price": 1}])
    b3 = models.get_batch(i3)
    ck("剩 15 米（1.5% < 3%）自动算发完", b3["state"] == "已发完",
       f"{b3['state']} left={b3['left_meters']}")

    services.save_inbound(cid, "2026-08-05", "", [
        {"dye_lot": "T1004", "fabric_id": fid, "color": "绿", "rolls": 0, "meters": 1000}])
    i4 = [x for x in models.list_batches(cid) if x["dye_lot"] == "T1004"][0]["item_id"]
    p5, _ = services.save_production({
        "customer_id": cid, "inbound_item_id": i4, "done_date": "2026-08-06",
        "process_id": procs["白膜"], "rolls": 0, "meters": 900})
    services.save_shipment(cid, "2026-08-07", "", "", "", [
        {"inbound_item_id": i4, "production_id": p5, "process_id": procs["白膜"],
         "rolls": 0, "meters": 900, "unit_price": 1}])
    b4 = models.get_batch(i4)
    ck("剩 100 米（10% > 3%）仍是部分发货", b4["state"] == "部分发货",
       f"{b4['state']} left={b4['left_meters']}")

    print("\n[11] 全厂成品库存表")
    fin = services.finished_stock(only_open=True)
    lots = {f["dye_lot"] for f in fin}
    ck("T1002 有成品在厂", "T1002" in lots, lots)
    ck("已发完的不出现", "T1001" not in lots, lots)
    ck("成品行带客户名", all(f["customer"] for f in fin))

    print("\n[12] 加工记录的删除保护")
    try:
        models.delete_production(p3)
        ck("发过货的成品不能删", True)   # p3 未发货，应能删
    except ValueError:
        ck("p3 未发货应可删", False)
    try:
        models.delete_production(p4)
        ck("发过货的成品应拒删", False)
    except ValueError as e:
        ck("发过货的成品拒删", True)
        ck("提示先删发货单", "发货单" in str(e), str(e))

    print("\n[12b] 只挂成品、不挂缸号的发货，也要把坯布库存扣下来")
    # 老账本导入走的是这条路：一行进仓 → 一条加工 → 一笔发货，发货只挂成品。
    # 视图早先只认 shipment_item.inbound_item_id，这种发货的米数扣不下来，
    # 鹏川 203 万米会一直挂在库存上。
    c2 = models.save_customer({"name": "鹏川纺织", "opening_balance": 0})
    services.save_inbound(c2, "2026-03-07", "", [
        {"dye_lot": "0307-陆琴良335尼龙斜", "fabric_id": fid, "rolls": 45,
         "meters": 3633}])
    b2 = models.list_batches(c2)[0]
    p5 = services.save_production({
        "customer_id": c2, "inbound_item_id": b2["item_id"], "done_date": "2026-03-07",
        "process_id": procs["白膜"], "rolls": 45, "meters": 3633})[0]
    services.save_shipment(c2, "2026-03-14", "", "", "", [
        {"production_id": p5, "process_id": procs["白膜"],
         "rolls": 45, "meters": 3633, "unit_price": 1.9}])   # 故意不传 inbound_item_id
    b2 = models.get_batch(b2["item_id"])
    show(b2, "只挂成品发货")
    ck("已发算到缸上 3633 米", abs(b2["out_meters"] - 3633) < 0.01, b2["out_meters"])
    ck("剩余归零", abs(b2["left_meters"]) < 0.01, b2["left_meters"])
    ck("成品待发归零", abs(b2["fin_meters"]) < 0.01, b2["fin_meters"])
    ck("状态已发完", b2["state"] == "已发完", b2["state"])
    bal2 = models.get_customer_balance(c2)
    ck("客户库存归零", abs(bal2["stock_meters"]) < 0.01, bal2["stock_meters"])
    ck("应收 6902.70", abs(bal2["billed"] - 6902.7) < 0.01, bal2["billed"])

    print("\n[13] 老库升级（v1 → v2）")
    old = os.path.join(TMP, "old.db")
    import sqlite3
    c = sqlite3.connect(old)
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE schema_version(version INTEGER NOT NULL);
        INSERT INTO schema_version VALUES (1);
        CREATE TABLE customer(id INTEGER PRIMARY KEY, code TEXT, name TEXT NOT NULL,
            contact TEXT, phone TEXT, address TEXT,
            opening_balance REAL NOT NULL DEFAULT 0, opening_date TEXT,
            note TEXT, active INTEGER NOT NULL DEFAULT 1, created_at TEXT);
        INSERT INTO customer(id,name,opening_balance) VALUES (1,'老客户',100);
        CREATE TABLE shipment_item(id INTEGER PRIMARY KEY, shipment_id INTEGER,
            inbound_item_id INTEGER, process_id INTEGER, rolls INTEGER DEFAULT 0,
            meters REAL DEFAULT 0, unit_price REAL DEFAULT 0, amount REAL DEFAULT 0,
            note TEXT);
    """)
    c.commit()
    db.init_schema(c)
    cols = {r["name"] for r in c.execute("PRAGMA table_info(customer)")}
    ck("升级后 customer 有 use_dye_lot", "use_dye_lot" in cols)
    ck("升级后 customer 有 track_weight", "track_weight" in cols)
    scols = {r["name"] for r in c.execute("PRAGMA table_info(shipment_item)")}
    ck("升级后 shipment_item 有 production_id", "production_id" in scols)
    ck("升级后 shipment_item 有 weight", "weight" in scols)
    ck("升级后建出 production 表",
       c.execute("SELECT name FROM sqlite_master WHERE name='production'").fetchone()
       is not None)
    ck("老数据还在",
       c.execute("SELECT name FROM customer WHERE id=1").fetchone()["name"] == "老客户")
    ck("老客户默认按缸号管",
       c.execute("SELECT use_dye_lot u FROM customer WHERE id=1").fetchone()["u"] == 1)
    ck("版本号升到 2",
       c.execute("SELECT version v FROM schema_version").fetchone()["v"] == 2)
    ck("视图可查", c.execute("SELECT COUNT(*) FROM v_finished_stock").fetchone()
       is not None)
    c.close()

    print("\n" + "=" * 56)
    print(f"通过 {PASS}，失败 {FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        db.close_conn()
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(code)
