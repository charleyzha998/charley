# -*- coding: utf-8 -*-
"""另一台电脑数据库安全合并测试。不会接触正式数据库。"""

import os
import shutil
import sqlite3
import tempfile

from app import backup, db, db_merge
from app.db_merge import MergeReport, _Engine


OK = FAIL = 0


def ck(label, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print("  ok   %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s %s" % (label, extra))


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    db.init_schema(conn)
    return conn


def one(conn, sql, args=()):
    return conn.execute(sql, args).fetchone()


def main():
    temp = tempfile.mkdtemp(prefix="ferp_merge_")
    target_path = os.path.join(temp, "target.db")
    source_path = os.path.join(temp, "source.db")
    target = connect(target_path)

    # 两边最初来自同一份账套。
    song = target.execute(
        "INSERT INTO customer(name,opening_balance) VALUES ('松权布业',0)").lastrowid
    di = target.execute(
        "INSERT INTO customer(name,opening_balance) VALUES ('帝阁',0)").lastrowid
    fabric = target.execute(
        "INSERT INTO fabric(name) VALUES ('威龙格')").lastrowid
    proc = one(target, "SELECT id FROM process WHERE name='复合'")["id"]
    target.execute(
        """INSERT INTO inbound(doc_no,customer_id,in_date,note,created_at)
           VALUES ('JC-20260817-001',?,'2026-08-17','共同旧数据','2026-08-17 09:00:00')""",
        (song,))
    old_head = target.execute("SELECT last_insert_rowid()").fetchone()[0]
    target.execute(
        """INSERT INTO inbound_item(inbound_id,customer_id,dye_lot,fabric_id,color,
           rolls,meters,status,note) VALUES (?,?,?,?,?,10,1000,'open','共同旧数据')""",
        (old_head, song, "OLD1", fabric, "黑色"))
    target.commit()
    source = connect(source_path)
    target.backup(source)

    # 服务器和离线会计在同一天各自开了 001 号单，必须自动重编而不能覆盖。
    target.execute(
        """INSERT INTO inbound(doc_no,customer_id,in_date,note,created_at)
           VALUES ('JC-20260818-001',?,'2026-08-18','服务器单','2026-08-18 09:00:00')""",
        (di,))
    target_head = target.execute("SELECT last_insert_rowid()").fetchone()[0]
    target.execute(
        """INSERT INTO inbound_item(inbound_id,customer_id,dye_lot,fabric_id,color,
           rolls,meters,status,note) VALUES (?,?,?,?,?,1,100,'open','')""",
        (target_head, di, "SERVER1", fabric, "白色"))
    target.execute(
        """INSERT INTO shipment(doc_no,customer_id,ship_date,created_at)
           VALUES ('FH-20260818-001',?,'2026-08-18','2026-08-18 10:00:00')""",
        (di,))
    target.commit()

    source.execute(
        """INSERT INTO inbound(doc_no,customer_id,in_date,note,created_at)
           VALUES ('JC-20260818-001',?,'2026-08-18','会计离线单','2026-08-18 09:30:00')""",
        (song,))
    source_head = source.execute("SELECT last_insert_rowid()").fetchone()[0]
    source.execute(
        """INSERT INTO inbound_item(inbound_id,customer_id,dye_lot,fabric_id,color,
           rolls,meters,status,note) VALUES (?,?,?,?,?,12,1888,'open','会计新增')""",
        (source_head, song, "4824", fabric, "绿卡"))
    source_item = source.execute("SELECT last_insert_rowid()").fetchone()[0]
    source.execute(
        "INSERT INTO roll(inbound_item_id,seq,meters,note) VALUES (?,?,?,?)",
        (source_item, 1, 158.0, "第一卷"))
    source.execute(
        """INSERT INTO production(customer_id,inbound_item_id,done_date,process_id,
           fabric_id,color,rolls,meters,note,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (song, source_item, "2026-08-18", proc, fabric, "绿卡", 12, 1800,
         "会计新增", "2026-08-18 11:00:00"))
    source_prod = source.execute("SELECT last_insert_rowid()").fetchone()[0]
    source.execute(
        """INSERT INTO shipment(doc_no,customer_id,ship_date,note,created_at)
           VALUES ('FH-20260818-001',?,'2026-08-18','会计离线发货',
                   '2026-08-18 11:30:00')""", (song,))
    source_ship = source.execute("SELECT last_insert_rowid()").fetchone()[0]
    source.execute(
        """INSERT INTO shipment_item(shipment_id,inbound_item_id,production_id,
           fabric_id,color,process_id,rolls,meters,unit_price,amount,note)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (source_ship, source_item, source_prod, fabric, "绿卡", proc, 2, 300,
         1.5, 450, "会计新增"))
    source_si = source.execute("SELECT last_insert_rowid()").fetchone()[0]
    source.execute("UPDATE roll SET shipment_item_id=? WHERE inbound_item_id=?",
                   (source_si, source_item))
    source.execute(
        """INSERT INTO payment(customer_id,pay_date,amount,method,ref_no,note,created_at)
           VALUES (?,'2026-08-18',500,'转账','WX001','会计新增','2026-08-18 12:00:00')""",
        (song,))
    source.commit()

    print("=== 第一次合并 ===")
    report = MergeReport(source_path, "test")
    _Engine(source, target, report).run()
    ck("无冲突", report.ok, report.conflicts)
    ck("进仓单撞号后重编", any("进仓单" in x for x in report.renamed), report.renamed)
    ck("发货单撞号后重编", any("发货单" in x for x in report.renamed), report.renamed)
    ck("新增缸号 4824", report.added["缸号"] == 1, report.added)
    ck("预览列出 4824 和威龙格",
       any("4824" in x and "威龙格" in x for x in report.details), report.details)
    ck("新增加工", report.added["加工"] == 1, report.added)
    ck("新增发货", report.added["发货单"] == 1, report.added)
    ck("新增收款", report.added["收款"] == 1, report.added)
    target.commit()

    row = one(target, """SELECT ii.*,f.name fabric,c.name customer
                          FROM inbound_item ii JOIN customer c ON c.id=ii.customer_id
                          LEFT JOIN fabric f ON f.id=ii.fabric_id
                          WHERE c.name='松权布业' AND ii.dye_lot='4824'""")
    ck("4824 归到松权布业", row and row["customer"] == "松权布业")
    ck("4824 面料为威龙格", row and row["fabric"] == "威龙格")
    ck("4824 米数正确", row and row["meters"] == 1888)
    ck("服务器原单未覆盖",
       one(target, "SELECT customer_id FROM inbound WHERE doc_no='JC-20260818-001'")
       ["customer_id"] == di)
    ck("离线进仓单变成 002",
       one(target, "SELECT 1 ok FROM inbound WHERE doc_no='JC-20260818-002'") is not None)
    ck("卷码发货关联保留",
       one(target, "SELECT shipment_item_id FROM roll WHERE inbound_item_id=?",
           (row["id"],))["shipment_item_id"] is not None)

    print("\n=== 重复合并 ===")
    again = MergeReport(source_path, "test")
    _Engine(source, target, again).run()
    ck("第二次没有新增", again.total_added == 0, again.added)
    ck("第二次没有冲突", again.ok, again.conflicts)
    target.rollback()

    print("\n=== 同缸号内容冲突 ===")
    source.execute("UPDATE inbound_item SET meters=1889 WHERE id=?", (source_item,))
    source.commit()
    conflict = MergeReport(source_path, "test2")
    _Engine(source, target, conflict).run()
    ck("不同米数被拦截", not conflict.ok and
       any("4824" in x for x in conflict.conflicts), conflict.conflicts)
    target.rollback()

    source.close()
    target.close()

    print("\n=== 完整预览、备份、合并、日志流程 ===")
    live = os.path.join(temp, "live")
    os.makedirs(os.path.join(live, "data"))
    official_path = os.path.join(live, "data", "fabric_erp.db")
    source2_path = os.path.join(temp, "accountant.db")
    shutil.copy2(target_path, official_path)
    shutil.copy2(target_path, source2_path)
    source2 = connect(source2_path)
    song2 = one(source2, "SELECT id FROM customer WHERE name='松权布业'")["id"]
    source2.execute(
        """INSERT INTO payment(customer_id,pay_date,amount,method,ref_no,note,created_at)
           VALUES (?,'2026-08-19',888,'转账','FULL001','完整流程','2026-08-19 08:00:00')""",
        (song2,))
    source2.commit()
    source2.close()

    db.close_conn()
    db.DATA_DIR = os.path.join(live, "data")
    db.DB_PATH = official_path
    db.CLIENT_CFG = os.path.join(live, "client.json")
    backup.BACKUP_DIR = os.path.join(live, "backups")
    preview = db_merge.analyze_database(source2_path)
    ck("完整流程预览通过", preview.ok, preview.conflicts)
    ck("预览发现一条新收款", preview.added["收款"] == 1, preview.added)
    result = db_merge.merge_database(
        source2_path, preview.confirmation_key(), preview.fingerprint)
    ck("合并前备份存在", os.path.isfile(result.backup_path), result.backup_path)
    ck("合并日志存在", os.path.isfile(result.log_path), result.log_path)
    ck("正式库收到收款",
       one(db.local_conn(), "SELECT 1 ok FROM payment WHERE ref_no='FULL001'") is not None)
    preview2 = db_merge.analyze_database(source2_path)
    ck("完整流程可重复执行", preview2.total_added == 0, preview2.added)
    db.close_conn()

    print("\n合计：%d 通过，%d 失败" % (OK, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
