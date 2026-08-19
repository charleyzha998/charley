"""各表 CRUD + 视图查询。SQL 集中在这里，UI 层不写 SQL。"""

from .db import get_conn, transaction


# ---------------- 客户 ----------------

def list_customers(keyword=""):
    sql = "SELECT * FROM v_customer_balance"
    args = []
    if keyword:
        sql += " WHERE customer LIKE ?"
        args.append(f"%{keyword}%")
    sql += " ORDER BY customer"
    return get_conn().execute(sql, args).fetchall()


def get_customer(cid):
    return get_conn().execute("SELECT * FROM customer WHERE id=?", (cid,)).fetchone()


def get_customer_balance(cid):
    return get_conn().execute(
        "SELECT * FROM v_customer_balance WHERE customer_id=?", (cid,)).fetchone()


def save_customer(data, cid=None):
    fields = ("code", "name", "contact", "phone", "address",
              "opening_balance", "opening_date", "use_dye_lot", "track_weight", "note")
    vals = [data.get(f) for f in fields]
    # 两个开关默认：按缸号管库存、不记重量
    vals[fields.index("use_dye_lot")] = int(data.get("use_dye_lot", 1) or 0)
    vals[fields.index("track_weight")] = int(data.get("track_weight", 0) or 0)
    with transaction() as conn:
        if cid:
            conn.execute(
                f"UPDATE customer SET {','.join(f + '=?' for f in fields)} WHERE id=?",
                vals + [cid])
            return cid
        cur = conn.execute(
            f"INSERT INTO customer({','.join(fields)}) VALUES ({','.join('?' * len(fields))})",
            vals)
        return cur.lastrowid


def delete_customer(cid):
    """仅当该客户无任何单据时才允许删除。"""
    conn = get_conn()
    for tbl, col in (("inbound", "customer_id"), ("shipment", "customer_id"),
                     ("production", "customer_id"), ("payment", "customer_id")):
        n = conn.execute(f"SELECT COUNT(*) c FROM {tbl} WHERE {col}=?", (cid,)).fetchone()["c"]
        if n:
            raise ValueError("该客户已有单据，不能删除。可改名或停用。")
    with transaction() as c:
        c.execute("DELETE FROM customer WHERE id=?", (cid,))


# ---------------- 面料 / 工艺 ----------------

def list_fabrics():
    return get_conn().execute(
        "SELECT * FROM fabric WHERE active=1 ORDER BY name").fetchall()


def list_processes():
    return get_conn().execute(
        "SELECT * FROM process WHERE active=1 ORDER BY name").fetchall()


def save_fabric(name, spec=None, note=None, fid=None):
    with transaction() as conn:
        if fid:
            conn.execute("UPDATE fabric SET name=?, spec=?, note=? WHERE id=?",
                         (name, spec, note, fid))
            return fid
        cur = conn.execute("INSERT INTO fabric(name, spec, note) VALUES (?,?,?)",
                           (name, spec, note))
        return cur.lastrowid


def save_process(name, note=None, pid=None):
    with transaction() as conn:
        if pid:
            conn.execute("UPDATE process SET name=?, note=? WHERE id=?", (name, note, pid))
            return pid
        cur = conn.execute("INSERT INTO process(name, note) VALUES (?,?)", (name, note))
        return cur.lastrowid


def get_or_create_fabric(name):
    """面料输入框允许直接输入新名称，自动建档。"""
    name = (name or "").strip()
    if not name:
        return None
    row = get_conn().execute("SELECT id FROM fabric WHERE name=?", (name,)).fetchone()
    if row:
        return row["id"]
    return save_fabric(name)


def deactivate(table, rid):
    assert table in ("fabric", "process")
    with transaction() as conn:
        conn.execute(f"UPDATE {table} SET active=0 WHERE id=?", (rid,))


# ---------------- 价格表 ----------------

def list_prices(customer_id=None):
    sql = """SELECT p.*, c.name AS customer, IFNULL(f.name,'(通用)') AS fabric,
                    pr.name AS process
             FROM price p
             JOIN customer c ON c.id = p.customer_id
             LEFT JOIN fabric f ON f.id = p.fabric_id
             JOIN process pr ON pr.id = p.process_id"""
    args = []
    if customer_id:
        sql += " WHERE p.customer_id=?"
        args.append(customer_id)
    sql += " ORDER BY c.name, fabric, pr.name, p.effective_date DESC"
    return get_conn().execute(sql, args).fetchall()


def save_price(customer_id, fabric_id, process_id, unit_price, effective_date,
               note=None, pid=None):
    with transaction() as conn:
        if pid:
            conn.execute("""UPDATE price SET customer_id=?, fabric_id=?, process_id=?,
                            unit_price=?, effective_date=?, note=? WHERE id=?""",
                         (customer_id, fabric_id, process_id, unit_price,
                          effective_date, note, pid))
            return pid
        cur = conn.execute("""INSERT INTO price(customer_id, fabric_id, process_id,
                              unit_price, effective_date, note) VALUES (?,?,?,?,?,?)""",
                           (customer_id, fabric_id, process_id, unit_price,
                            effective_date, note))
        return cur.lastrowid


def delete_price(pid):
    with transaction() as conn:
        conn.execute("DELETE FROM price WHERE id=?", (pid,))


# ---------------- 进仓 ----------------

def list_batches(customer_id, keyword="", only_open=False):
    sql = "SELECT * FROM v_batch_stock WHERE customer_id=?"
    args = [customer_id]
    if keyword:
        sql += " AND (dye_lot LIKE ? OR fabric LIKE ? OR color LIKE ?)"
        args += [f"%{keyword}%"] * 3
    if only_open:
        sql += " AND state IN ('未加工','待发货','部分发货')"
    sql += " ORDER BY in_date DESC, dye_lot DESC"
    return get_conn().execute(sql, args).fetchall()


def get_batch(item_id):
    return get_conn().execute(
        "SELECT * FROM v_batch_stock WHERE item_id=?", (item_id,)).fetchone()


def list_inbounds(customer_id):
    return get_conn().execute(
        """SELECT ib.*, COUNT(ii.id) AS n_items,
                  IFNULL(SUM(ii.rolls),0) AS rolls, IFNULL(SUM(ii.meters),0) AS meters
           FROM inbound ib LEFT JOIN inbound_item ii ON ii.inbound_id = ib.id
           WHERE ib.customer_id=? AND ib.deleted=0
           GROUP BY ib.id ORDER BY ib.in_date DESC, ib.id DESC""",
        (customer_id,)).fetchall()


def get_inbound(iid):
    conn = get_conn()
    head = conn.execute("SELECT * FROM inbound WHERE id=?", (iid,)).fetchone()
    items = conn.execute(
        """SELECT ii.*, IFNULL(f.name,'') AS fabric FROM inbound_item ii
           LEFT JOIN fabric f ON f.id = ii.fabric_id
           WHERE ii.inbound_id=? ORDER BY ii.id""", (iid,)).fetchall()
    return head, items


def list_rolls(item_id):
    return get_conn().execute(
        "SELECT * FROM roll WHERE inbound_item_id=? ORDER BY seq", (item_id,)).fetchall()


def set_batch_status(item_id, status):
    with transaction() as conn:
        conn.execute("UPDATE inbound_item SET status=? WHERE id=?", (status, item_id))


# ---------------- 发货 ----------------

def list_shipments(customer_id, date_from=None, date_to=None):
    sql = """SELECT sh.*, COUNT(si.id) AS n_items,
                    IFNULL(SUM(si.rolls),0)  AS rolls,
                    IFNULL(SUM(si.meters),0) AS meters,
                    IFNULL(SUM(si.amount),0) AS amount
             FROM shipment sh LEFT JOIN shipment_item si ON si.shipment_id = sh.id
             WHERE sh.customer_id=? AND sh.deleted=0"""
    args = [customer_id]
    if date_from:
        sql += " AND sh.ship_date >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND sh.ship_date <= ?"
        args.append(date_to)
    sql += " GROUP BY sh.id ORDER BY sh.ship_date DESC, sh.id DESC"
    return get_conn().execute(sql, args).fetchall()


def get_shipment(sid):
    conn = get_conn()
    head = conn.execute(
        """SELECT sh.*, c.name AS customer FROM shipment sh
           JOIN customer c ON c.id = sh.customer_id WHERE sh.id=?""", (sid,)).fetchone()
    items = conn.execute(
        """SELECT si.*, IFNULL(ii.dye_lot,'') AS dye_lot,
                  IFNULL(NULLIF(si.color,''), IFNULL(ii.color,'')) AS color,
                  IFNULL(sf.name, IFNULL(f.name,'')) AS fabric,
                  IFNULL(p.name,'') AS process
           FROM shipment_item si
           LEFT JOIN inbound_item ii ON ii.id = si.inbound_item_id
           LEFT JOIN fabric f  ON f.id = ii.fabric_id
           LEFT JOIN fabric sf ON sf.id = si.fabric_id
           LEFT JOIN process p ON p.id = si.process_id
           WHERE si.shipment_id=? ORDER BY si.id""", (sid,)).fetchall()
    return head, items


def list_shipment_items(customer_id, date_from=None, date_to=None):
    """对账单明细：按发货日期区间列出所有行。"""
    sql = """SELECT sh.doc_no, sh.ship_date, IFNULL(ii.dye_lot,'') AS dye_lot,
                    IFNULL(sf.name, IFNULL(f.name,'')) AS fabric,
                    IFNULL(NULLIF(si.color,''), IFNULL(ii.color,'')) AS color,
                    IFNULL(p.name,'') AS process,
                    si.rolls, si.meters, si.weight,
                    si.unit_price, si.amount, IFNULL(si.note,'') AS note
             FROM shipment_item si
             JOIN shipment sh     ON sh.id = si.shipment_id AND sh.deleted = 0
             LEFT JOIN inbound_item ii ON ii.id = si.inbound_item_id
             LEFT JOIN fabric f   ON f.id = ii.fabric_id
             LEFT JOIN fabric sf  ON sf.id = si.fabric_id
             LEFT JOIN process p  ON p.id = si.process_id
             WHERE sh.customer_id=?"""
    args = [customer_id]
    if date_from:
        sql += " AND sh.ship_date >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND sh.ship_date <= ?"
        args.append(date_to)
    sql += " ORDER BY sh.ship_date, sh.id, si.id"
    return get_conn().execute(sql, args).fetchall()


# ---------------- 加工完成 / 成品库存 ----------------

def list_finished(customer_id=None, keyword="", only_open=False):
    """成品库存：加工好了、还没发（或没发完）的。"""
    sql = "SELECT * FROM v_finished_stock WHERE 1=1"
    args = []
    if customer_id:
        sql += " AND customer_id=?"
        args.append(customer_id)
    if only_open:
        sql += " AND state IN ('待发货','部分发货')"
    if keyword:
        sql += " AND (customer LIKE ? OR dye_lot LIKE ? OR fabric LIKE ? OR color LIKE ?)"
        args += [f"%{keyword}%"] * 4
    sql += " ORDER BY done_date DESC, prod_id DESC"
    return get_conn().execute(sql, args).fetchall()


def get_finished(prod_id):
    return get_conn().execute(
        "SELECT * FROM v_finished_stock WHERE prod_id=?", (prod_id,)).fetchone()


def list_productions_of_batch(item_id):
    """某一缸的历次加工记录。"""
    return get_conn().execute(
        "SELECT * FROM v_finished_stock WHERE item_id=? ORDER BY done_date, prod_id",
        (item_id,)).fetchall()


def save_production(data, prod_id=None):
    """data: customer_id, inbound_item_id(可空), done_date, process_id, fabric_id,
    color, rolls, meters, weight, note"""
    fields = ("customer_id", "inbound_item_id", "done_date", "process_id",
              "fabric_id", "color", "rolls", "meters", "weight", "note")
    vals = [data.get(f) for f in fields]
    vals[fields.index("rolls")] = int(data.get("rolls") or 0)
    vals[fields.index("meters")] = float(data.get("meters") or 0)
    with transaction() as conn:
        if prod_id:
            conn.execute(
                f"UPDATE production SET {','.join(f + '=?' for f in fields)} WHERE id=?",
                vals + [prod_id])
            return prod_id
        cur = conn.execute(
            f"INSERT INTO production({','.join(fields)}) "
            f"VALUES ({','.join('?' * len(fields))})", vals)
        return cur.lastrowid


def delete_production(prod_id):
    """已经按这条成品发过货的，不允许删。"""
    n = get_conn().execute(
        """SELECT COUNT(*) c FROM shipment_item si
           JOIN shipment sh ON sh.id = si.shipment_id AND sh.deleted=0
           WHERE si.production_id=?""", (prod_id,)).fetchone()["c"]
    if n:
        raise ValueError("这条加工记录已经发过货，不能删除。请先删掉相关发货单。")
    with transaction() as conn:
        conn.execute("UPDATE production SET deleted=1 WHERE id=?", (prod_id,))


# ---------------- 收款 ----------------

def list_payments(customer_id, date_from=None, date_to=None):
    sql = "SELECT * FROM payment WHERE customer_id=? AND deleted=0"
    args = [customer_id]
    if date_from:
        sql += " AND pay_date >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND pay_date <= ?"
        args.append(date_to)
    sql += " ORDER BY pay_date DESC, id DESC"
    return get_conn().execute(sql, args).fetchall()


def save_payment(customer_id, pay_date, amount, method, ref_no=None, note=None, pid=None):
    with transaction() as conn:
        if pid:
            conn.execute("""UPDATE payment SET pay_date=?, amount=?, method=?,
                            ref_no=?, note=? WHERE id=?""",
                         (pay_date, amount, method, ref_no, note, pid))
            return pid
        cur = conn.execute("""INSERT INTO payment(customer_id, pay_date, amount, method,
                              ref_no, note) VALUES (?,?,?,?,?,?)""",
                           (customer_id, pay_date, amount, method, ref_no, note))
        return cur.lastrowid


def delete_payment(pid):
    with transaction() as conn:
        conn.execute("UPDATE payment SET deleted=1 WHERE id=?", (pid,))


# ---------------- 软删除单据 ----------------

def delete_inbound(iid):
    """有发货或加工记录的进仓单不允许删除。"""
    conn = get_conn()
    n = conn.execute(
        """SELECT COUNT(*) c FROM shipment_item si
           JOIN inbound_item ii ON ii.id = si.inbound_item_id
           JOIN shipment sh ON sh.id = si.shipment_id AND sh.deleted=0
           WHERE ii.inbound_id=?""", (iid,)).fetchone()["c"]
    if n:
        raise ValueError("该进仓单下已有发货记录，不能删除。请先删除相关发货单。")
    n = conn.execute(
        """SELECT COUNT(*) c FROM production p
           JOIN inbound_item ii ON ii.id = p.inbound_item_id
           WHERE ii.inbound_id=? AND p.deleted=0""", (iid,)).fetchone()["c"]
    if n:
        raise ValueError("该进仓单下已有加工记录，不能删除。请先删除相关加工记录。")
    with transaction() as conn:
        conn.execute("UPDATE inbound SET deleted=1 WHERE id=?", (iid,))


def delete_shipment(sid):
    with transaction() as conn:
        conn.execute("UPDATE roll SET shipment_item_id=NULL WHERE shipment_item_id IN "
                     "(SELECT id FROM shipment_item WHERE shipment_id=?)", (sid,))
        conn.execute("UPDATE shipment SET deleted=1 WHERE id=?", (sid,))


# ---------------- 自动补全用的历史值 ----------------

def distinct_colors(customer_id=None, limit=200):
    sql = "SELECT DISTINCT color FROM inbound_item WHERE color IS NOT NULL AND color<>''"
    args = []
    if customer_id:
        sql += " AND customer_id=?"
        args.append(customer_id)
    sql += f" ORDER BY color LIMIT {int(limit)}"
    return [r["color"] for r in get_conn().execute(sql, args).fetchall()]
