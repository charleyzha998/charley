"""数据库连接、建表、视图、迁移。

设计要点：
- 库存不存字段，由 v_batch_stock 视图实时聚合（进仓 - 发货）
- 金额/单价落库快照，价格表改价不影响历史单据
- 缸号在同一客户内唯一（唯一索引保证）
"""

import os
import sqlite3
import sys
from contextlib import contextmanager

SCHEMA_VERSION = 2


def app_dir():
    """程序所在目录。打包成 exe 后返回 exe 所在目录，
    否则 __file__ 会指向 PyInstaller 的临时解压目录，数据会丢。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


_APP_DIR = app_dir()
DATA_DIR = os.path.join(_APP_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "fabric_erp.db")

_conn = None            # 业务代码用的：可能是本地库，也可能是远程服务器
_local = None           # 本地库文件的连接：服务器自己用，见 local_conn()


def get_conn():
    """返回全局单例连接。

    两种模式：
      · 单机 / 服务器本机 —— 直接开本地的 fabric_erp.db（默认）
      · 客户端（会计那台）—— 连到服务器上，见 remote_db.py。
        业务代码分辨不出区别，照样 execute。
    """
    global _conn
    if _conn is None:
        cfg = _client_config()
        if cfg:
            from .remote_db import RemoteConnection
            _conn = RemoteConnection(cfg["host"], cfg["port"], cfg["token"])
        else:
            _conn = local_conn()
    return _conn


def local_conn():
    """本机那个数据库文件的连接，跟客户端配置无关。

    服务器要用它 —— 服务器如果走 get_conn()，而这台电脑又配成了客户端，
    请求就会绕回自己，两边互相等着，界面直接卡死（实测就是超时）。
    """
    global _local
    if _local is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        # check_same_thread=False：开了服务器模式以后，别人的请求是在各自的
        # 线程里进来的，都用这一个连接。安全靠 server.py 里那把大锁 ——
        # 同一时刻只让一个请求碰库，跟单机没区别。
        c = sqlite3.connect(DB_PATH, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        c.execute("PRAGMA journal_mode = WAL")
        init_schema(c)
        _local = c
    return _local


# 连服务器的配置存在 exe 同级的 client.json 里（不放数据库 ——
# 库本身就在服务器上，鸡生蛋的问题）。
CLIENT_CFG = os.path.join(_APP_DIR, "client.json")


def _client_config():
    """读客户端配置。没这个文件就是单机模式。"""
    if not os.path.exists(CLIENT_CFG):
        return None
    try:
        import json
        with open(CLIENT_CFG, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return None
    if not cfg.get("enabled") or not cfg.get("host"):
        return None
    cfg.setdefault("port", 8756)
    cfg.setdefault("token", "")
    return cfg


def save_client_config(host, port, token, enabled=True):
    """写客户端配置。改完要重启软件才生效（连接是启动时建的）。

    写完立刻读回来核对。写不进去（装在 Program Files 这种要管理员权限的
    地方、或者被同步盘锁着）在 Windows 上有时不报错，只是没写成 —— 那样
    会计以为设好了，重启一看又变回「本机管数据」，等于悄悄记了两套账。
    所以宁可当场抛出来。
    """
    import json
    data = {"enabled": bool(enabled), "host": host,
            "port": int(port), "token": token}
    os.makedirs(os.path.dirname(CLIENT_CFG) or ".", exist_ok=True)
    with open(CLIENT_CFG, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())          # 断电/强关也得留住
    back = None
    try:
        with open(CLIENT_CFG, encoding="utf-8") as f:
            back = json.load(f)
    except Exception as e:
        raise OSError("设置写进 %s 了，但读不回来：%s" % (CLIENT_CFG, e))
    if back != data:
        raise OSError("设置没能存到 %s —— 读回来的跟写进去的不一样。"
                      "这个目录可能不允许写（比如装在 C:\\Program Files 下面）。"
                      % CLIENT_CFG)


def is_client():
    return _client_config() is not None


def close_conn(local=True):
    """关连接。local=False 只断远程那条，本地库照旧 —— 服务器在跑的时候
    不能把自己脚下的库关掉。"""
    global _conn, _local
    if _conn is not None and _conn is not _local:
        _conn.close()
    _conn = None
    if local and _local is not None:
        _local.close()
        _local = None


@contextmanager
def transaction():
    """事务上下文：出错自动回滚。

    提交前顺手把 data_rev 加一 —— 界面靠它判断「库里有没有人动过东西」，
    有变化才重读。查一个整数比把所有列表都重查一遍便宜得多，
    两台电脑共用时可以几秒问一次。
    """
    conn = get_conn()
    if hasattr(conn, "begin"):
        conn.begin()        # 连的是服务器：告诉它这一段要攒着一起提交
    try:
        yield conn
        conn.execute(
            "UPDATE app_setting SET value = CAST("
            "  CAST(value AS INTEGER) + 1 AS TEXT) WHERE key = 'data_rev'")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def data_rev():
    """库里的改动次数。变了说明有人（可能是另一台电脑）存了东西。

    读不到就返回 -1：宁可这一轮不刷，也不要因为一句查询失败弹一堆错。
    """
    try:
        row = get_conn().execute(
            "SELECT value FROM app_setting WHERE key = 'data_rev'").fetchone()
    except Exception:
        return -1
    if not row:
        return -1
    try:
        return int(row["value"] if not isinstance(row, tuple) else row[0])
    except (TypeError, ValueError):
        return -1


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS customer (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT,
    name            TEXT NOT NULL,
    contact         TEXT,
    phone           TEXT,
    address         TEXT,
    opening_balance REAL NOT NULL DEFAULT 0,   -- 期初欠款
    opening_date    TEXT,
    use_dye_lot     INTEGER NOT NULL DEFAULT 1, -- 1=按缸号管库存, 0=做完直接发不管库存
    track_weight    INTEGER NOT NULL DEFAULT 0, -- 1=记录重量KG
    note            TEXT,
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_customer_name ON customer(name);

CREATE TABLE IF NOT EXISTS fabric (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL,
    spec    TEXT,                              -- 克重/门幅
    note    TEXT,
    active  INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_fabric_name ON fabric(name);

CREATE TABLE IF NOT EXISTS process (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL,
    note    TEXT,
    active  INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_process_name ON process(name);

-- 价格表：客户 + 面料 + 工艺 三维，按 effective_date 取最新生效价
CREATE TABLE IF NOT EXISTS price (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id    INTEGER NOT NULL REFERENCES customer(id) ON DELETE CASCADE,
    fabric_id      INTEGER REFERENCES fabric(id) ON DELETE CASCADE,
    process_id     INTEGER NOT NULL REFERENCES process(id) ON DELETE CASCADE,
    unit_price     REAL NOT NULL,
    effective_date TEXT NOT NULL,
    note           TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_price
    ON price(customer_id, IFNULL(fabric_id,-1), process_id, effective_date);

CREATE TABLE IF NOT EXISTS inbound (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_no      TEXT NOT NULL,
    customer_id INTEGER NOT NULL REFERENCES customer(id),
    in_date     TEXT NOT NULL,
    note        TEXT,
    deleted     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_inbound_doc ON inbound(doc_no);
CREATE INDEX IF NOT EXISTS ix_inbound_cust ON inbound(customer_id, in_date);

CREATE TABLE IF NOT EXISTS inbound_item (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    inbound_id  INTEGER NOT NULL REFERENCES inbound(id) ON DELETE CASCADE,
    customer_id INTEGER NOT NULL REFERENCES customer(id),  -- 冗余，为缸号唯一索引服务
    dye_lot     TEXT NOT NULL,                  -- 缸号
    fabric_id   INTEGER REFERENCES fabric(id),
    color       TEXT,
    rolls       INTEGER NOT NULL DEFAULT 0,     -- 可为 0：有些客户只记米数
    meters      REAL NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'open',   -- open / closed(已结清)
    note        TEXT
);
-- 缸号同一客户内唯一
CREATE UNIQUE INDEX IF NOT EXISTS ux_item_lot ON inbound_item(customer_id, dye_lot);
CREATE INDEX IF NOT EXISTS ix_item_inbound ON inbound_item(inbound_id);

-- 逐卷码单（可选录入）
CREATE TABLE IF NOT EXISTS roll (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    inbound_item_id  INTEGER NOT NULL REFERENCES inbound_item(id) ON DELETE CASCADE,
    seq              INTEGER NOT NULL,          -- 卷号
    meters           REAL NOT NULL DEFAULT 0,
    shipment_item_id INTEGER REFERENCES shipment_item(id) ON DELETE SET NULL,  -- NULL=在库
    note             TEXT
);
CREATE INDEX IF NOT EXISTS ix_roll_item ON roll(inbound_item_id);

-- 加工完成（成品入库）：坯布做好了但还没发。
-- 这是「厂里压了多少做好的货」的来源。
CREATE TABLE IF NOT EXISTS production (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id     INTEGER NOT NULL REFERENCES customer(id),
    inbound_item_id INTEGER REFERENCES inbound_item(id) ON DELETE CASCADE, -- 无缸号客户可空
    done_date       TEXT NOT NULL,              -- 加工完成日期
    process_id      INTEGER REFERENCES process(id),
    fabric_id       INTEGER REFERENCES fabric(id),   -- 无缸号时自己填
    color           TEXT,
    rolls           INTEGER NOT NULL DEFAULT 0, -- 成品卷数/支数
    meters          REAL NOT NULL DEFAULT 0,    -- 成品米数
    weight          REAL,                       -- 重量 KG，选填
    note            TEXT,
    deleted         INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_prod_cust ON production(customer_id, done_date);
CREATE INDEX IF NOT EXISTS ix_prod_item ON production(inbound_item_id);

CREATE TABLE IF NOT EXISTS shipment (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_no      TEXT NOT NULL,
    customer_id INTEGER NOT NULL REFERENCES customer(id),
    ship_date   TEXT NOT NULL,
    receiver    TEXT,
    plate_no    TEXT,
    note        TEXT,
    deleted     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_shipment_doc ON shipment(doc_no);
CREATE INDEX IF NOT EXISTS ix_shipment_cust ON shipment(customer_id, ship_date);

CREATE TABLE IF NOT EXISTS shipment_item (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_id     INTEGER NOT NULL REFERENCES shipment(id) ON DELETE CASCADE,
    inbound_item_id INTEGER REFERENCES inbound_item(id),   -- 无缸号客户可空
    production_id   INTEGER REFERENCES production(id),     -- 从成品库发货时指向它
    fabric_id       INTEGER REFERENCES fabric(id),         -- 无缸号时自己填
    color           TEXT,
    process_id      INTEGER REFERENCES process(id),
    rolls           INTEGER NOT NULL DEFAULT 0,
    meters          REAL NOT NULL DEFAULT 0,
    weight          REAL,                       -- 重量 KG，选填
    unit_price      REAL NOT NULL DEFAULT 0,    -- 快照
    amount          REAL NOT NULL DEFAULT 0,    -- 快照
    note            TEXT
);
CREATE INDEX IF NOT EXISTS ix_sitem_ship ON shipment_item(shipment_id);
CREATE INDEX IF NOT EXISTS ix_sitem_batch ON shipment_item(inbound_item_id);

CREATE TABLE IF NOT EXISTS payment (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customer(id) ON DELETE CASCADE,
    pay_date    TEXT NOT NULL,
    amount      REAL NOT NULL,
    method      TEXT NOT NULL DEFAULT '转账',   -- 现金/转账/承兑/抵扣
    ref_no      TEXT,
    note        TEXT,
    deleted     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_payment_cust ON payment(customer_id, pay_date);

CREATE TABLE IF NOT EXISTS app_setting (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# 引用了 v2 新列的索引：必须等迁移补完列再建，否则老库启动会炸
LATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS ix_sitem_prod ON shipment_item(production_id);
"""

# 视图：每次启动重建，方便随代码演进
VIEW_SQL = """
-- 缸号库存：坯布 → 成品 → 已发 三段
DROP VIEW IF EXISTS v_batch_stock;
CREATE VIEW v_batch_stock AS
SELECT
    ii.id                AS item_id,
    ii.customer_id       AS customer_id,
    c.name               AS customer,
    ib.doc_no            AS in_doc_no,
    ib.in_date           AS in_date,
    ii.dye_lot           AS dye_lot,
    IFNULL(f.name,'')    AS fabric,
    IFNULL(ii.color,'')  AS color,
    ii.rolls             AS in_rolls,
    ii.meters            AS in_meters,
    IFNULL(pr.rolls,0)   AS done_rolls,
    IFNULL(pr.meters,0)  AS done_meters,
    IFNULL(s.rolls,0)    AS out_rolls,
    IFNULL(s.meters,0)   AS out_meters,
    -- 坯布库存：进仓了还没加工的
    ii.rolls - IFNULL(pr.rolls,0)                      AS greige_rolls,
    ROUND(ii.meters - IFNULL(pr.meters,0), 2)          AS greige_meters,
    -- 成品库存：加工好还没发的（厂里压着的货）
    IFNULL(pr.rolls,0) - IFNULL(s.rolls,0)             AS fin_rolls,
    ROUND(IFNULL(pr.meters,0) - IFNULL(s.meters,0), 2) AS fin_meters,
    -- 总剩余：进仓减已发
    ii.rolls - IFNULL(s.rolls,0)                       AS left_rolls,
    ROUND(ii.meters - IFNULL(s.meters,0), 2)           AS left_meters,
    -- 状态：有卷数按卷数判；没卷数按米数留零头判
    CASE
        WHEN ii.status = 'closed' THEN '已结清'
        WHEN ii.rolls > 0 AND ii.rolls - IFNULL(s.rolls,0) <= 0 THEN '已发完'
        WHEN ii.rolls = 0 AND IFNULL(s.meters,0) > 0 AND ii.meters > 0
             AND (ii.meters - IFNULL(s.meters,0)) <= ii.meters *
                 CAST(IFNULL((SELECT value FROM app_setting WHERE key='remnant_pct'),'3')
                      AS REAL) / 100.0
             THEN '已发完'
        WHEN IFNULL(s.rolls,0) = 0 AND IFNULL(s.meters,0) = 0
             THEN CASE WHEN IFNULL(pr.meters,0) > 0 THEN '待发货' ELSE '未加工' END
        ELSE '部分发货'
    END AS state,
    -- 缩率%：发完才有意义
    CASE WHEN ii.meters > 0 AND IFNULL(s.meters,0) > 0
              AND ((ii.rolls > 0 AND ii.rolls - IFNULL(s.rolls,0) <= 0)
                   OR (ii.rolls = 0 AND ii.status = 'closed'))
         THEN ROUND((ii.meters - IFNULL(s.meters,0)) * 100.0 / ii.meters, 2)
         ELSE NULL END AS shrink_pct,
    ii.status            AS status,
    IFNULL(ii.note,'')   AS note
FROM inbound_item ii
JOIN inbound  ib ON ib.id = ii.inbound_id AND ib.deleted = 0
JOIN customer c  ON c.id  = ii.customer_id
LEFT JOIN fabric f ON f.id = ii.fabric_id
LEFT JOIN (
    SELECT p.inbound_item_id AS iid,
           SUM(p.rolls) AS rolls, SUM(p.meters) AS meters
    FROM production p
    WHERE p.deleted = 0 AND p.inbound_item_id IS NOT NULL
    GROUP BY p.inbound_item_id
) pr ON pr.iid = ii.id
LEFT JOIN (
    -- 发货有两种挂法，都要算进来，否则库存扣不下去：
    --   ① 直接挂缸号（库存表点某一缸发货 → inbound_item_id）
    --   ② 挂成品（先加工好、再从成品发 → production_id，缸号靠成品带出来）
    -- 鹏川就是第二种：一行进仓 → 一条加工 → 一笔发货。少算 ② 的话
    -- 进仓的米数会永远挂在库存上下不来。
    SELECT iid, SUM(rolls) AS rolls, SUM(meters) AS meters FROM (
        SELECT si.inbound_item_id AS iid, si.rolls AS rolls, si.meters AS meters
        FROM shipment_item si
        JOIN shipment sh ON sh.id = si.shipment_id AND sh.deleted = 0
        WHERE si.inbound_item_id IS NOT NULL
        UNION ALL
        SELECT p.inbound_item_id AS iid, si.rolls AS rolls, si.meters AS meters
        FROM shipment_item si
        JOIN shipment sh ON sh.id = si.shipment_id AND sh.deleted = 0
        JOIN production p ON p.id = si.production_id AND p.deleted = 0
        WHERE si.inbound_item_id IS NULL AND p.inbound_item_id IS NOT NULL
    ) GROUP BY iid
) s ON s.iid = ii.id;

-- 成品库存：加工好还没发的（含无缸号客户）
DROP VIEW IF EXISTS v_finished_stock;
CREATE VIEW v_finished_stock AS
SELECT
    p.id                 AS prod_id,
    p.customer_id        AS customer_id,
    c.name               AS customer,
    p.inbound_item_id    AS item_id,
    p.done_date          AS done_date,
    IFNULL(ii.dye_lot,'') AS dye_lot,
    IFNULL(f.name, IFNULL(f2.name,'')) AS fabric,
    IFNULL(NULLIF(p.color,''), IFNULL(ii.color,'')) AS color,
    IFNULL(pc.name,'')   AS process,
    p.rolls              AS done_rolls,
    p.meters             AS done_meters,
    p.weight             AS weight,
    IFNULL(s.rolls,0)    AS out_rolls,
    IFNULL(s.meters,0)   AS out_meters,
    p.rolls - IFNULL(s.rolls,0)                        AS left_rolls,
    ROUND(p.meters - IFNULL(s.meters,0), 2)            AS left_meters,
    CASE WHEN p.rolls > 0 AND p.rolls - IFNULL(s.rolls,0) <= 0 THEN '已发完'
         WHEN p.rolls = 0 AND IFNULL(s.meters,0) > 0 AND p.meters > 0
              AND (p.meters - IFNULL(s.meters,0)) <= p.meters *
                  CAST(IFNULL((SELECT value FROM app_setting WHERE key='remnant_pct'),'3')
                       AS REAL) / 100.0
              THEN '已发完'
         WHEN p.rolls = 0 AND p.meters - IFNULL(s.meters,0) <= 0.01 THEN '已发完'
         WHEN IFNULL(s.meters,0) = 0 AND IFNULL(s.rolls,0) = 0 THEN '待发货'
         ELSE '部分发货' END AS state,
    IFNULL(p.note,'')    AS note
FROM production p
JOIN customer c ON c.id = p.customer_id
LEFT JOIN inbound_item ii ON ii.id = p.inbound_item_id
LEFT JOIN fabric f  ON f.id  = p.fabric_id
LEFT JOIN fabric f2 ON f2.id = ii.fabric_id
LEFT JOIN process pc ON pc.id = p.process_id
LEFT JOIN (
    SELECT si.production_id AS pid,
           SUM(si.rolls) AS rolls, SUM(si.meters) AS meters
    FROM shipment_item si
    JOIN shipment sh ON sh.id = si.shipment_id AND sh.deleted = 0
    WHERE si.production_id IS NOT NULL
    GROUP BY si.production_id
) s ON s.pid = p.id
WHERE p.deleted = 0;

DROP VIEW IF EXISTS v_customer_balance;
CREATE VIEW v_customer_balance AS
SELECT
    c.id                                   AS customer_id,
    c.name                                 AS customer,
    IFNULL(c.phone,'')                     AS phone,
    IFNULL(c.contact,'')                   AS contact,
    c.use_dye_lot                          AS use_dye_lot,
    c.opening_balance                      AS opening_balance,
    IFNULL(b.amount, 0)                    AS billed,
    IFNULL(p.paid, 0)                      AS paid,
    ROUND(c.opening_balance + IFNULL(b.amount,0) - IFNULL(p.paid,0), 2) AS balance,
    IFNULL(st.open_batches, 0)             AS open_batches,
    ROUND(IFNULL(st.stock_meters, 0), 2)   AS stock_meters,
    ROUND(IFNULL(fs.fin_meters, 0), 2)     AS fin_meters
FROM customer c
LEFT JOIN (
    SELECT sh.customer_id AS cid, SUM(si.amount) AS amount
    FROM shipment_item si
    JOIN shipment sh ON sh.id = si.shipment_id AND sh.deleted = 0
    GROUP BY sh.customer_id
) b ON b.cid = c.id
LEFT JOIN (
    SELECT customer_id AS cid, SUM(amount) AS paid
    FROM payment WHERE deleted = 0 GROUP BY customer_id
) p ON p.cid = c.id
LEFT JOIN (
    SELECT customer_id AS cid,
           COUNT(*) AS open_batches, SUM(left_meters) AS stock_meters
    FROM v_batch_stock
    WHERE state IN ('未加工','待发货','部分发货')
    GROUP BY customer_id
) st ON st.cid = c.id
LEFT JOIN (
    -- 只算还没发完的；发完了剩下的那点米数是缩率，不是货
    SELECT customer_id AS cid, SUM(left_meters) AS fin_meters
    FROM v_finished_stock
    WHERE state IN ('待发货','部分发货')
    GROUP BY customer_id
) fs ON fs.cid = c.id;
"""

DEFAULT_SETTINGS = {
    "company_name": "",
    "company_address": "",
    "company_phone": "",
    "company_bank": "",
    "billing_basis": "out",     # out=按发货米计费, in=按进仓米计费
    "shrink_warn_pct": "8",     # 缩率超过该值标黄
    "remnant_pct": "3",         # 无卷数的缸，剩余低于进仓的百分之几算发完
    "backup_keep": "30",
    # 服务器模式：这台电脑要不要开服务给别人连。口令首次开服务时自动生成。
    "server_enabled": "0",
    "server_port": "8756",
    "server_token": "",
    # 存一次东西加一。界面隔几秒看一眼这个数，变了才重读 —— 见 transaction()
    "data_rev": "0",
}

# 工艺预置：复合加工（把布料粘合在一起）——贴膜类 + 贴布类，
# 另加账本里出现过的克重复合与切边。新工艺在「基础资料」里随时能加。
DEFAULT_PROCESSES = ["贴白膜", "贴黑膜", "贴透明膜", "贴低透明膜", "贴布",
                     "白膜", "黑膜", "透明膜", "低透明", "PE膜",
                     "复合", "60克复合", "70克复合", "80克复合", "100克复合",
                     "单切边", "双切边", "防水"]


def init_schema(conn):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    old = None
    if row:
        r = conn.execute("SELECT version FROM schema_version").fetchone()
        old = r["version"] if r else None

    conn.executescript(SCHEMA_SQL)
    if old is not None:
        _migrate(conn, old)          # 补列要在建索引/视图之前，它们会引用新列
    conn.executescript(LATE_INDEX_SQL)
    conn.executescript(VIEW_SQL)

    if conn.execute("SELECT COUNT(*) c FROM schema_version").fetchone()["c"] == 0:
        conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))

    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO app_setting(key, value) VALUES (?,?)", (k, v))

    if conn.execute("SELECT COUNT(*) c FROM process").fetchone()["c"] == 0:
        conn.executemany("INSERT INTO process(name) VALUES (?)",
                         [(p,) for p in DEFAULT_PROCESSES])
    conn.commit()


def _add_column(conn, table, col, decl):
    """给已存在的表补列（SQLite 没有 ADD COLUMN IF NOT EXISTS）。"""
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def _migrate(conn, from_version):
    """老库升级。v1 → v2：加工段（成品库存）+ 无缸号客户 + 支数重量。"""
    if from_version < 2:
        _add_column(conn, "customer", "use_dye_lot", "INTEGER NOT NULL DEFAULT 1")
        _add_column(conn, "customer", "track_weight", "INTEGER NOT NULL DEFAULT 0")
        _add_column(conn, "shipment_item", "production_id", "INTEGER")
        _add_column(conn, "shipment_item", "fabric_id", "INTEGER")
        _add_column(conn, "shipment_item", "color", "TEXT")
        _add_column(conn, "shipment_item", "weight", "REAL")
        # 早期版本预置的是染整工艺（染色/定型/磨毛…），本厂做的是复合贴膜。
        # 老库补进贴膜工艺；已经用过的旧工艺留着不删，免得历史单据的工艺名变空。
        have = {r["name"] for r in conn.execute("SELECT name FROM process")}
        conn.executemany("INSERT INTO process(name) VALUES (?)",
                         [(p,) for p in DEFAULT_PROCESSES if p not in have])
    _relax_ship_item(conn)
    conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))


def _relax_ship_item(conn):
    """v1 的 shipment_item.inbound_item_id 是 NOT NULL —— 必须拆掉。

    v1 只有「进仓 → 发货」两段，每笔发货必然挂着一缸，所以当时写了 NOT NULL。
    v2 加了成品段和无缸号客户，发货有三种挂法：挂缸号、挂成品、什么都不挂
    （逸峰这种做完直接发的）。后两种在老库上会被这条约束顶回来，报
    「NOT NULL constraint failed」，整笔发货存不进去 —— 应收就凭空少了。

    SQLite 没法 ALTER 掉 NOT NULL，只能照官方推荐的办法重建表：
    建新表 → 搬数据 → 删旧表 → 改名。索引和视图后面会统一重建。
    """
    ddl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='shipment_item'"
    ).fetchone()
    if not ddl:
        return
    text = ddl["sql"] if not isinstance(ddl, tuple) else ddl[0]
    if "inbound_item_id INTEGER NOT NULL" not in text.replace("  ", " "):
        return                       # 已经是可空的，不用动

    cols = [r["name"] for r in conn.execute("PRAGMA table_info(shipment_item)")]
    keep = [c for c in cols if c != "id"]

    # 视图引用了这张表，不先删掉的话 DROP TABLE 会报
    # 「error in view v_batch_stock: no such table」。反正 init_schema
    # 紧接着就会用 VIEW_SQL 全部重建。
    for v in [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view'")]:
        conn.execute("DROP VIEW IF EXISTS %s" % v)

    conn.executescript("""
        PRAGMA foreign_keys = OFF;
        CREATE TABLE shipment_item_new (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_id     INTEGER NOT NULL REFERENCES shipment(id) ON DELETE CASCADE,
            inbound_item_id INTEGER REFERENCES inbound_item(id),
            production_id   INTEGER REFERENCES production(id),
            fabric_id       INTEGER REFERENCES fabric(id),
            color           TEXT,
            process_id      INTEGER REFERENCES process(id),
            rolls           INTEGER NOT NULL DEFAULT 0,
            meters          REAL NOT NULL DEFAULT 0,
            weight          REAL,
            unit_price      REAL NOT NULL DEFAULT 0,
            amount          REAL NOT NULL DEFAULT 0,
            note            TEXT
        );""")
    conn.execute("INSERT INTO shipment_item_new(id,%s) SELECT id,%s FROM shipment_item"
                 % (",".join(keep), ",".join(keep)))
    conn.executescript("""
        DROP TABLE shipment_item;
        ALTER TABLE shipment_item_new RENAME TO shipment_item;
        PRAGMA foreign_keys = ON;""")


# ---------- 设置读写 ----------

def get_setting(key, default=""):
    row = get_conn().execute("SELECT value FROM app_setting WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    with transaction() as conn:
        conn.execute(
            "INSERT INTO app_setting(key,value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)))
