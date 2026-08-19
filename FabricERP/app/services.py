"""业务逻辑：单号生成、单据保存（事务）、价格查询、对账汇总、缩率校验。"""

from datetime import date

from .db import get_conn, get_setting, transaction
from . import models

METHODS = ("现金", "转账", "承兑", "抵扣", "其他")


def today_str():
    return date.today().strftime("%Y-%m-%d")


def money(x):
    """金额规整到 2 位小数。"""
    return round(float(x or 0) + 1e-9, 2)


# ---------------- 单号 ----------------

def next_doc_no(kind, on_date=None, conn=None):
    """kind: 'JC'(进仓) / 'FH'(发货)。格式 JC-20260813-001，按日流水。

    必须在写入事务内调用，避免并发重号。
    """
    prefix = {"JC": "JC", "FH": "FH"}[kind]
    table = {"JC": "inbound", "FH": "shipment"}[kind]
    d = (on_date or today_str()).replace("-", "")
    head = f"{prefix}-{d}-"
    c = conn or get_conn()
    row = c.execute(
        f"SELECT doc_no FROM {table} WHERE doc_no LIKE ? ORDER BY doc_no DESC LIMIT 1",
        (head + "%",)).fetchone()
    seq = int(row["doc_no"].rsplit("-", 1)[1]) + 1 if row else 1
    return f"{head}{seq:03d}"


# ---------------- 价格 ----------------

def lookup_price(customer_id, fabric_id, process_id, on_date=None):
    """取生效价：优先 客户+面料+工艺，其次 客户+通用面料+工艺。
    同组合取 effective_date <= on_date 的最新一条。
    """
    on_date = on_date or today_str()
    conn = get_conn()
    for fid_cond, args_extra in ((("fabric_id = ?"), [fabric_id]),
                                 (("fabric_id IS NULL"), [])):
        if fid_cond == "fabric_id = ?" and fabric_id is None:
            continue
        row = conn.execute(
            f"""SELECT unit_price FROM price
                WHERE customer_id=? AND process_id=? AND {fid_cond}
                  AND effective_date <= ?
                ORDER BY effective_date DESC, id DESC LIMIT 1""",
            [customer_id, process_id] + args_extra + [on_date]).fetchone()
        if row:
            return row["unit_price"]
    return None


# ---------------- 进仓保存 ----------------

def save_inbound(customer_id, in_date, note, items, inbound_id=None):
    """items: [{dye_lot, fabric_id, color, rolls, meters, note, rolls_detail:[米数,...]}]

    整单事务：重建明细。已有发货的缸号不允许删除或改缸号。
    """
    if not items:
        raise ValueError("至少要有一行进仓明细。")

    lots = [str(it["dye_lot"]).strip() for it in items]
    if any(not x for x in lots):
        raise ValueError("缸号不能为空。")
    dup = {x for x in lots if lots.count(x) > 1}
    if dup:
        raise ValueError(f"本单内缸号重复：{'、'.join(sorted(dup))}")

    with transaction() as conn:
        if inbound_id:
            _guard_inbound_edit(conn, inbound_id, items)
            conn.execute("UPDATE inbound SET in_date=?, note=? WHERE id=?",
                         (in_date, note, inbound_id))
            # 只删掉本次没有提交的缸号；已发货/已加工的缸号在 _guard_inbound_edit 里已拦住
            keep_ids = [it["id"] for it in items if it.get("id")]
            if keep_ids:
                ph = ",".join("?" * len(keep_ids))
                conn.execute(
                    f"DELETE FROM inbound_item WHERE inbound_id=? AND id NOT IN ({ph})",
                    [inbound_id] + keep_ids)
            else:
                conn.execute("DELETE FROM inbound_item WHERE inbound_id=?",
                             (inbound_id,))
        else:
            doc_no = next_doc_no("JC", in_date, conn)
            cur = conn.execute(
                "INSERT INTO inbound(doc_no, customer_id, in_date, note) VALUES (?,?,?,?)",
                (doc_no, customer_id, in_date, note))
            inbound_id = cur.lastrowid

        for it in items:
            _check_lot_unique(conn, customer_id, it["dye_lot"], it.get("id"))
            if it.get("id"):
                conn.execute(
                    """UPDATE inbound_item SET dye_lot=?, fabric_id=?, color=?,
                       rolls=?, meters=?, note=? WHERE id=?""",
                    (it["dye_lot"].strip(), it.get("fabric_id"), it.get("color"),
                     int(it.get("rolls") or 0), float(it.get("meters") or 0),
                     it.get("note"), it["id"]))
                item_id = it["id"]
            else:
                cur = conn.execute(
                    """INSERT INTO inbound_item(inbound_id, customer_id, dye_lot,
                       fabric_id, color, rolls, meters, note) VALUES (?,?,?,?,?,?,?,?)""",
                    (inbound_id, customer_id, it["dye_lot"].strip(), it.get("fabric_id"),
                     it.get("color"), int(it.get("rolls") or 0),
                     float(it.get("meters") or 0), it.get("note")))
                item_id = cur.lastrowid

            detail = it.get("rolls_detail")
            if detail is not None:
                conn.execute("DELETE FROM roll WHERE inbound_item_id=? "
                             "AND shipment_item_id IS NULL", (item_id,))
                conn.executemany(
                    "INSERT INTO roll(inbound_item_id, seq, meters) VALUES (?,?,?)",
                    [(item_id, i + 1, float(m or 0)) for i, m in enumerate(detail)])
    return inbound_id


def _check_lot_unique(conn, customer_id, dye_lot, item_id=None):
    sql = "SELECT id FROM inbound_item WHERE customer_id=? AND dye_lot=?"
    args = [customer_id, str(dye_lot).strip()]
    if item_id:
        sql += " AND id<>?"
        args.append(item_id)
    if conn.execute(sql, args).fetchone():
        raise ValueError(f"缸号 {dye_lot} 在该客户下已存在，请换一个。")


def _guard_inbound_edit(conn, inbound_id, items):
    """已有发货或加工记录的缸号不能被删掉。"""
    keep = {it.get("id") for it in items if it.get("id")}

    shipped = conn.execute(
        """SELECT ii.id, ii.dye_lot FROM inbound_item ii
           WHERE ii.inbound_id=? AND ii.id IN
                 (SELECT DISTINCT inbound_item_id FROM shipment_item)""",
        (inbound_id,)).fetchall()
    gone = [r["dye_lot"] for r in shipped if r["id"] not in keep]
    if gone:
        raise ValueError(f"缸号 {'、'.join(gone)} 已有发货记录，不能删除。")

    produced = conn.execute(
        """SELECT ii.id, ii.dye_lot FROM inbound_item ii
           WHERE ii.inbound_id=? AND ii.id IN
                 (SELECT DISTINCT inbound_item_id FROM production
                  WHERE inbound_item_id IS NOT NULL AND deleted=0)""",
        (inbound_id,)).fetchall()
    gone = [r["dye_lot"] for r in produced if r["id"] not in keep]
    if gone:
        raise ValueError(
            f"缸号 {'、'.join(gone)} 已有加工记录，不能删除。请先删除相关加工记录。")


# ---------------- 发货保存 ----------------

def save_shipment(customer_id, ship_date, receiver, plate_no, note, items,
                  shipment_id=None, force=False):
    """items: [{inbound_item_id?, production_id?, fabric_id?, color?, process_id,
                rolls, meters, weight?, unit_price, note}]

    缸号(inbound_item_id)与成品(production_id)都可为空 —— 无缸号客户直接填面料发货。
    返回 (shipment_id, warnings)。force=False 时超发抛异常，force=True 时记录警告放行。
    """
    if not items:
        raise ValueError("至少要有一行发货明细。")

    warnings = _check_overship(customer_id, items, shipment_id)
    if warnings and not force:
        raise OvershipError(warnings)

    with transaction() as conn:
        if shipment_id:
            conn.execute("""UPDATE shipment SET ship_date=?, receiver=?, plate_no=?,
                            note=? WHERE id=?""",
                         (ship_date, receiver, plate_no, note, shipment_id))
            conn.execute("UPDATE roll SET shipment_item_id=NULL WHERE shipment_item_id IN "
                         "(SELECT id FROM shipment_item WHERE shipment_id=?)", (shipment_id,))
            conn.execute("DELETE FROM shipment_item WHERE shipment_id=?", (shipment_id,))
        else:
            doc_no = next_doc_no("FH", ship_date, conn)
            cur = conn.execute(
                """INSERT INTO shipment(doc_no, customer_id, ship_date, receiver,
                   plate_no, note) VALUES (?,?,?,?,?,?)""",
                (doc_no, customer_id, ship_date, receiver, plate_no, note))
            shipment_id = cur.lastrowid

        for it in items:
            rolls = int(it.get("rolls") or 0)
            meters = float(it.get("meters") or 0)
            price = float(it.get("unit_price") or 0)
            weight = it.get("weight")
            amount = money(_billing_meters(conn, it, meters) * price)
            conn.execute(
                """INSERT INTO shipment_item(shipment_id, inbound_item_id, production_id,
                   fabric_id, color, process_id, rolls, meters, weight,
                   unit_price, amount, note)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (shipment_id, it.get("inbound_item_id"), it.get("production_id"),
                 it.get("fabric_id"), it.get("color"), it.get("process_id"),
                 rolls, meters, float(weight) if weight not in (None, "") else None,
                 price, amount, it.get("note")))
    return shipment_id, warnings


def _billing_meters(conn, item, out_meters):
    """计费基数：默认按发货米；设置为 'in' 时按该缸进仓米（仅一次性全发时有意义）。"""
    if get_setting("billing_basis", "out") != "in":
        return out_meters
    iid = item.get("inbound_item_id")
    if not iid:
        return out_meters
    row = conn.execute("SELECT meters, rolls FROM inbound_item WHERE id=?",
                       (iid,)).fetchone()
    if not row or not row["rolls"]:
        return out_meters
    # 按发货卷数占比折算进仓米
    return row["meters"] * (int(item.get("rolls") or 0) / row["rolls"])


class OvershipError(Exception):
    def __init__(self, warnings):
        super().__init__("；".join(warnings))
        self.warnings = warnings


def _check_overship(customer_id, items, exclude_shipment_id=None):
    """超发检查。指定了成品的按成品剩余比，只指定缸号的按该缸剩余比，
    两者都没有（无缸号客户直接发）不检查。返回警告文案列表。"""
    conn = get_conn()
    warns = []
    by_lot, by_prod = {}, {}
    for it in items:
        rolls = int(it.get("rolls") or 0)
        meters = float(it.get("meters") or 0)
        if it.get("production_id"):
            r, m = by_prod.get(it["production_id"], (0, 0.0))
            by_prod[it["production_id"]] = (r + rolls, m + meters)
        elif it.get("inbound_item_id"):
            r, m = by_lot.get(it["inbound_item_id"], (0, 0.0))
            by_lot[it["inbound_item_id"]] = (r + rolls, m + meters)

    for pid, (rolls, meters) in by_prod.items():
        row = conn.execute(
            """SELECT p.rolls, p.meters, IFNULL(ii.dye_lot,'') AS dye_lot,
                      IFNULL(s.rolls,0) AS out_rolls, IFNULL(s.meters,0) AS out_meters
               FROM production p
               LEFT JOIN inbound_item ii ON ii.id = p.inbound_item_id
               LEFT JOIN (SELECT si.production_id pid, SUM(si.rolls) rolls,
                                 SUM(si.meters) meters
                          FROM shipment_item si
                          JOIN shipment sh ON sh.id=si.shipment_id AND sh.deleted=0
                          WHERE si.shipment_id IS NOT ?
                          GROUP BY si.production_id) s ON s.pid = p.id
               WHERE p.id=?""", (exclude_shipment_id, pid)).fetchone()
        if not row:
            continue
        what = f"缸号 {row['dye_lot']} 的成品" if row["dye_lot"] else "这批成品"
        left_rolls = row["rolls"] - row["out_rolls"]
        left_meters = row["meters"] - row["out_meters"]
        if row["rolls"] and rolls > left_rolls:
            warns.append(f"{what}：发 {rolls} 卷，成品仅剩 {left_rolls} 卷")
        if meters > left_meters + 0.01:
            warns.append(f"{what}：发 {meters:g} 米，成品仅剩 {left_meters:.2f} 米")

    for iid, (rolls, meters) in by_lot.items():
        row = conn.execute(
            """SELECT ii.dye_lot, ii.rolls, ii.meters,
                      IFNULL(s.rolls,0) AS out_rolls, IFNULL(s.meters,0) AS out_meters
               FROM inbound_item ii
               LEFT JOIN (SELECT si.inbound_item_id iid, SUM(si.rolls) rolls,
                                 SUM(si.meters) meters
                          FROM shipment_item si
                          JOIN shipment sh ON sh.id=si.shipment_id AND sh.deleted=0
                          WHERE si.shipment_id IS NOT ?
                          GROUP BY si.inbound_item_id) s ON s.iid = ii.id
               WHERE ii.id=?""", (exclude_shipment_id, iid)).fetchone()
        if not row:
            continue
        left_rolls = row["rolls"] - row["out_rolls"]
        left_meters = row["meters"] - row["out_meters"]
        if row["rolls"] and rolls > left_rolls:
            warns.append(f"缸号 {row['dye_lot']}：发 {rolls} 卷，剩余仅 {left_rolls} 卷")
        if meters > left_meters + 0.01:
            warns.append(
                f"缸号 {row['dye_lot']}：发 {meters:g} 米，剩余仅 {left_meters:.2f} 米")
    return warns


def shrink_warn_pct():
    try:
        return float(get_setting("shrink_warn_pct", "8"))
    except ValueError:
        return 8.0


def is_shrink_abnormal(shrink_pct):
    """缩率为负（发货多于进仓）或超过阈值，都视为异常需要标黄。"""
    if shrink_pct is None:
        return False
    return shrink_pct < 0 or shrink_pct > shrink_warn_pct()


# ---------------- 对账 ----------------

def statement(customer_id, date_from=None, date_to=None):
    """三段式对账：期初 + 本期应收 - 本期已收 = 期末应收。

    期初 = 客户期初欠款 + 起始日之前的发货合计 - 起始日之前的收款合计
    """
    conn = get_conn()
    cust = models.get_customer(customer_id)
    opening = float(cust["opening_balance"] or 0)

    if date_from:
        prev_billed = conn.execute(
            """SELECT IFNULL(SUM(si.amount),0) a FROM shipment_item si
               JOIN shipment sh ON sh.id=si.shipment_id AND sh.deleted=0
               WHERE sh.customer_id=? AND sh.ship_date < ?""",
            (customer_id, date_from)).fetchone()["a"]
        prev_paid = conn.execute(
            """SELECT IFNULL(SUM(amount),0) a FROM payment
               WHERE customer_id=? AND deleted=0 AND pay_date < ?""",
            (customer_id, date_from)).fetchone()["a"]
        opening = opening + prev_billed - prev_paid

    items = models.list_shipment_items(customer_id, date_from, date_to)
    payments = models.list_payments(customer_id, date_from, date_to)

    billed = money(sum(r["amount"] for r in items))
    paid = money(sum(r["amount"] for r in payments))

    return {
        "customer": cust,
        "date_from": date_from,
        "date_to": date_to,
        "opening": money(opening),
        "items": items,
        "payments": payments,
        "total_rolls": sum(r["rolls"] for r in items),
        "total_meters": round(sum(r["meters"] for r in items), 2),
        "billed": billed,
        "paid": paid,
        "closing": money(opening + billed - paid),
        "print_date": today_str(),
    }


# ---------------- 加工完成 ----------------

class OverproduceError(Exception):
    def __init__(self, warnings):
        super().__init__("；".join(warnings))
        self.warnings = warnings


def save_production(data, prod_id=None, force=False):
    """录一条「加工好了」。data 见 models.save_production。

    坯布不够（这一缸累计加工超过进仓量）时警告，force=True 放行。
    """
    if not float(data.get("meters") or 0) and not int(data.get("rolls") or 0):
        raise ValueError("加工的卷数和米数不能都是 0。")

    warns = _check_overproduce(data, prod_id)
    if warns and not force:
        raise OverproduceError(warns)
    return models.save_production(data, prod_id), warns


def _check_overproduce(data, exclude_prod_id=None):
    """这一缸已加工 + 本次 是否超过进仓量。无缸号的不检查。"""
    iid = data.get("inbound_item_id")
    if not iid:
        return []
    row = get_conn().execute(
        """SELECT ii.dye_lot, ii.rolls, ii.meters,
                  IFNULL((SELECT SUM(p.rolls) FROM production p
                          WHERE p.inbound_item_id=ii.id AND p.deleted=0
                            AND p.id IS NOT ?), 0) AS done_rolls,
                  IFNULL((SELECT SUM(p.meters) FROM production p
                          WHERE p.inbound_item_id=ii.id AND p.deleted=0
                            AND p.id IS NOT ?), 0) AS done_meters
           FROM inbound_item ii WHERE ii.id=?""",
        (exclude_prod_id, exclude_prod_id, iid)).fetchone()
    if not row:
        return []
    warns = []
    rolls = int(data.get("rolls") or 0)
    meters = float(data.get("meters") or 0)
    left_rolls = row["rolls"] - row["done_rolls"]
    left_meters = row["meters"] - row["done_meters"]
    if row["rolls"] and rolls > left_rolls:
        warns.append(f"缸号 {row['dye_lot']}：加工 {rolls} 卷，未加工的坯布只剩 {left_rolls} 卷")
    if meters > left_meters + 0.01:
        warns.append(
            f"缸号 {row['dye_lot']}：加工 {meters:g} 米，未加工的坯布只剩 {left_meters:.2f} 米")
    return warns


# ---------------- 全局库存 ----------------

def global_stock(keyword="", only_open=True):
    sql = "SELECT * FROM v_batch_stock WHERE 1=1"
    args = []
    if only_open:
        sql += " AND state IN ('未加工','待发货','部分发货')"
    if keyword:
        sql += " AND (customer LIKE ? OR dye_lot LIKE ? OR fabric LIKE ? OR color LIKE ?)"
        args += [f"%{keyword}%"] * 4
    sql += " ORDER BY customer, in_date DESC, dye_lot"
    return get_conn().execute(sql, args).fetchall()


def finished_stock(keyword="", only_open=True):
    """全厂成品库存：做好了还没发出去的货。"""
    return models.list_finished(None, keyword, only_open)
