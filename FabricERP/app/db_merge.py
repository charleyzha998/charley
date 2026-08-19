# -*- coding: utf-8 -*-
"""把另一台电脑的本地账套安全地、单向地合并进服务器账套。

这不是 SQLite 文件覆盖，也不是双向同步。规则是：

* 服务器数据永远保留；
* 主数据按名称映射；
* 缸号按「客户 + 缸号」识别；
* 单号相撞但内容不同，给导入单据重新编号；
* 完全相同的业务记录跳过，所以同一个库可以重复合并；
* 同一个业务键内容不同属于冲突，整次合并不落库。

真正写入前会在内存数据库里完整演练一次。用户确认后再次演练，确认服务器
和来源文件都没有变化，才备份并在一个事务里写入。
"""

import hashlib
import json
import os
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime

from . import backup, db


KINDS = ("客户", "面料", "工艺", "价格", "进仓单", "缸号", "卷码",
         "加工", "发货单", "发货明细", "收款")

REQUIRED_COLUMNS = {
    "customer": {"id", "name", "opening_balance", "use_dye_lot", "track_weight"},
    "fabric": {"id", "name"},
    "process": {"id", "name"},
    "price": {"id", "customer_id", "fabric_id", "process_id", "unit_price",
              "effective_date"},
    "inbound": {"id", "doc_no", "customer_id", "in_date", "deleted", "created_at"},
    "inbound_item": {"id", "inbound_id", "customer_id", "dye_lot", "fabric_id",
                     "rolls", "meters", "status"},
    "roll": {"id", "inbound_item_id", "seq", "meters", "shipment_item_id"},
    "production": {"id", "customer_id", "inbound_item_id", "done_date",
                   "process_id", "fabric_id", "rolls", "meters", "deleted",
                   "created_at"},
    "shipment": {"id", "doc_no", "customer_id", "ship_date", "deleted", "created_at"},
    "shipment_item": {"id", "shipment_id", "inbound_item_id", "production_id",
                      "fabric_id", "process_id", "rolls", "meters", "unit_price",
                      "amount"},
    "payment": {"id", "customer_id", "pay_date", "amount", "deleted", "created_at"},
    "schema_version": {"version"},
}


class MergeError(RuntimeError):
    """来源文件无效、预览失效或合并不能安全继续。"""


class MergeReport:
    def __init__(self, source_path="", fingerprint=""):
        self.source_path = os.path.abspath(source_path) if source_path else ""
        self.fingerprint = fingerprint
        self.added = Counter()
        self.duplicates = Counter()
        self.renamed = []
        self.details = []
        self.detail_omitted = 0
        self.warnings = []
        self.conflicts = []

    @property
    def ok(self):
        return not self.conflicts

    @property
    def total_added(self):
        return sum(self.added.values())

    def add(self, kind, n=1):
        self.added[kind] += n

    def duplicate(self, kind, n=1):
        self.duplicates[kind] += n

    def warn(self, text):
        if text not in self.warnings:
            self.warnings.append(text)

    def detail(self, text):
        """预览最多展示 100 条，旧整库不会把窗口塞进几千行。"""
        if len(self.details) < 100:
            self.details.append(text)
        else:
            self.detail_omitted += 1

    def conflict(self, text):
        if text not in self.conflicts:
            self.conflicts.append(text)

    def as_dict(self):
        return {
            "source_path": self.source_path,
            "fingerprint": self.fingerprint,
            "added": {k: self.added.get(k, 0) for k in KINDS if self.added.get(k)},
            "duplicates": {k: self.duplicates.get(k, 0)
                           for k in KINDS if self.duplicates.get(k)},
            "renamed": list(self.renamed),
            "details": list(self.details),
            "detail_omitted": self.detail_omitted,
            "warnings": list(self.warnings),
            "conflicts": list(self.conflicts),
        }

    def confirmation_key(self):
        """预览和真正写入前的演练必须得到完全相同的结论。"""
        data = self.as_dict().copy()
        data.pop("source_path", None)
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def text(self):
        lines = ["来源数据库：", self.source_path, ""]
        if self.added:
            lines.append("准备新增：")
            for kind in KINDS:
                if self.added.get(kind):
                    lines.append("  · %s：%d" % (kind, self.added[kind]))
        else:
            lines.append("准备新增：没有新记录")

        if self.duplicates:
            lines += ["", "已存在，将跳过："]
            for kind in KINDS:
                if self.duplicates.get(kind):
                    lines.append("  · %s：%d" % (kind, self.duplicates[kind]))

        if self.renamed:
            lines += ["", "单号撞车，将自动重编："]
            lines += ["  · " + x for x in self.renamed]

        if self.details:
            lines += ["", "准备新增的业务明细："]
            lines += ["  · " + x for x in self.details]
            if self.detail_omitted:
                lines.append("  · ……另有 %d 条未展开，请按上方分类数量核对。" %
                             self.detail_omitted)

        if self.warnings:
            lines += ["", "提醒（服务器现有资料优先，不会被覆盖）："]
            lines += ["  · " + x for x in self.warnings]

        if self.conflicts:
            lines += ["", "发现冲突，本次不能合并："]
            lines += ["  · " + x for x in self.conflicts]
        else:
            lines += ["", "检查通过。确认后会先自动备份，再整批写入。"]
        return "\n".join(lines)


@dataclass
class MergeResult:
    report: MergeReport
    backup_path: str
    log_path: str


def _dict(row):
    return dict(row) if row is not None else None


def _same(a, b, fields):
    return all(a.get(f) == b.get(f) for f in fields)


def _values(row, fields):
    return tuple(row.get(f) for f in fields)


def _insert(conn, table, data):
    cols = list(data)
    sql = "INSERT INTO %s(%s) VALUES (%s)" % (
        table, ",".join(cols), ",".join("?" for _ in cols))
    return conn.execute(sql, [data[c] for c in cols]).lastrowid


def _fingerprint(path):
    """主库和 WAL 一起算；会计没退出时，最新记录通常还在 WAL 里。"""
    h = hashlib.sha256()
    for suffix in ("", "-wal"):
        p = path + suffix
        h.update(suffix.encode("ascii"))
        if not os.path.exists(p):
            h.update(b"<missing>")
            continue
        st = os.stat(p)
        h.update(str(st.st_size).encode("ascii"))
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def _open_source(path):
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise MergeError("找不到数据库文件：%s" % path)
    try:
        if os.path.samefile(path, db.DB_PATH):
            raise MergeError("不能把当前服务器数据库合并到它自己。")
    except FileNotFoundError:
        pass
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"),
                               uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        _validate_source(conn)
        return conn
    except MergeError:
        raise
    except Exception as e:
        raise MergeError("打不开这个数据库：%s" % e)


def _validate_source(conn):
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    missing = sorted(set(REQUIRED_COLUMNS) - tables)
    if missing:
        raise MergeError("这不是可合并的 ERP 数据库，缺少数据表：%s" % "、".join(missing))
    for table, required in REQUIRED_COLUMNS.items():
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table)}
        miss = sorted(required - cols)
        if miss:
            raise MergeError("来源数据库版本太旧，%s 表缺少字段：%s" %
                             (table, "、".join(miss)))
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if not row or int(row["version"]) != db.SCHEMA_VERSION:
        got = row["version"] if row else "未知"
        raise MergeError("数据库版本不一致（来源 %s，本机 %s），请先用同版软件打开来源库。"
                         % (got, db.SCHEMA_VERSION))
    bad = conn.execute("PRAGMA integrity_check").fetchone()
    if not bad or bad[0] != "ok":
        raise MergeError("来源数据库完整性检查没有通过：%s" % (bad[0] if bad else "未知"))


class _Engine:
    def __init__(self, source, target, report):
        self.s = source
        self.t = target
        self.r = report
        self.customer = {}
        self.fabric = {None: None}
        self.process = {None: None}
        self.item = {None: None}
        self.production = {None: None}
        self.shipment_item = {None: None}
        self.roll = {}
        self._used_production = set()
        self._used_shipment = set()
        self._used_payment = set()

    def run(self):
        self._masters()
        self._prices()
        self._inbounds()
        self._rolls()
        self._productions()
        self._shipments()
        self._payments()
        self._link_rolls()
        return self.r

    # ---------- 主数据 ----------

    def _masters(self):
        self.customer = self._named_table(
            "customer", "客户",
            ("code", "name", "contact", "phone", "address", "opening_balance",
             "opening_date", "use_dye_lot", "track_weight", "note", "active",
             "created_at"),
            compare=("code", "contact", "phone", "address", "opening_balance",
                     "opening_date", "use_dye_lot", "track_weight", "note", "active"))
        self.fabric.update(self._named_table(
            "fabric", "面料", ("name", "spec", "note", "active"),
            compare=("spec", "note", "active")))
        self.process.update(self._named_table(
            "process", "工艺", ("name", "note", "active"),
            compare=("note", "active")))

    def _named_table(self, table, kind, insert_fields, compare):
        mapping = {}
        for sr in self.s.execute("SELECT * FROM %s ORDER BY id" % table):
            src = _dict(sr)
            tr = self.t.execute("SELECT * FROM %s WHERE name=?" % table,
                                (src["name"],)).fetchone()
            if tr is None:
                mapping[src["id"]] = _insert(
                    self.t, table, {f: src.get(f) for f in insert_fields})
                self.r.add(kind)
            else:
                target = _dict(tr)
                mapping[src["id"]] = target["id"]
                self.r.duplicate(kind)
                different = [f for f in compare if src.get(f) != target.get(f)]
                if different:
                    self.r.warn("%s「%s」的 %s 两边不同，保留服务器内容。" %
                                (kind, src["name"], "、".join(different)))
        return mapping

    # ---------- 价格 ----------

    def _prices(self):
        for sr in self.s.execute("SELECT * FROM price ORDER BY id"):
            src = _dict(sr)
            cid = self.customer[src["customer_id"]]
            fid = self.fabric.get(src["fabric_id"])
            pid = self.process.get(src["process_id"])
            tr = self.t.execute(
                """SELECT * FROM price WHERE customer_id=? AND fabric_id IS ?
                   AND process_id=? AND effective_date=?""",
                (cid, fid, pid, src["effective_date"])).fetchone()
            data = {"customer_id": cid, "fabric_id": fid, "process_id": pid,
                    "unit_price": src["unit_price"],
                    "effective_date": src["effective_date"], "note": src["note"]}
            if tr is None:
                _insert(self.t, "price", data)
                self.r.add("价格")
            else:
                self.r.duplicate("价格")
                target = _dict(tr)
                if not _same(data, target, ("unit_price", "note")):
                    self.r.warn("价格「客户ID %s / %s / %s / %s」两边不同，保留服务器价格。"
                                % (cid, fid or "通用", pid, src["effective_date"]))

    # ---------- 进仓和缸号 ----------

    def _inbounds(self):
        heads = self.s.execute(
            "SELECT * FROM inbound WHERE deleted=0 ORDER BY id").fetchall()
        for hr in heads:
            head = _dict(hr)
            cid = self.customer[head["customer_id"]]
            missing = []
            rows = self.s.execute(
                "SELECT * FROM inbound_item WHERE inbound_id=? ORDER BY id",
                (head["id"],)).fetchall()
            for ir in rows:
                src = _dict(ir)
                item_cid = self.customer[src["customer_id"]]
                if item_cid != cid:
                    self.r.conflict("进仓单 %s 的缸号 %s 客户归属不一致。" %
                                    (head["doc_no"], src["dye_lot"]))
                fid = self.fabric.get(src["fabric_id"])
                tr = self.t.execute(
                    "SELECT * FROM inbound_item WHERE customer_id=? AND dye_lot=?",
                    (item_cid, src["dye_lot"])).fetchone()
                payload = {"customer_id": item_cid, "dye_lot": src["dye_lot"],
                           "fabric_id": fid, "color": src["color"],
                           "rolls": src["rolls"], "meters": src["meters"],
                           "status": src["status"], "note": src["note"]}
                if tr is None:
                    missing.append((src, payload))
                    continue
                target = _dict(tr)
                self.item[src["id"]] = target["id"]
                fields = ("customer_id", "dye_lot", "fabric_id", "color", "rolls",
                          "meters", "status", "note")
                if _same(payload, target, fields):
                    self.r.duplicate("缸号")
                else:
                    diffs = [f for f in fields if payload.get(f) != target.get(f)]
                    self.r.conflict("客户「%s」缸号「%s」已存在，但 %s 不同。" %
                                    (self._customer_name(cid), src["dye_lot"],
                                     "、".join(diffs)))

            if not missing:
                if rows:
                    self.r.duplicate("进仓单")
                continue

            target_head = self.t.execute(
                "SELECT * FROM inbound WHERE doc_no=?", (head["doc_no"],)).fetchone()
            reuse = False
            if target_head is not None:
                th = _dict(target_head)
                reuse = _same(
                    {"customer_id": cid, "in_date": head["in_date"],
                     "note": head["note"], "deleted": 0}, th,
                    ("customer_id", "in_date", "note", "deleted"))
            if reuse:
                target_inbound_id = target_head["id"]
                self.r.duplicate("进仓单")
            else:
                doc_no = head["doc_no"]
                if target_head is not None:
                    new_no = self._next_doc_no("inbound", "JC", head["in_date"])
                    self.r.renamed.append("进仓单 %s → %s" % (doc_no, new_no))
                    doc_no = new_no
                target_inbound_id = _insert(self.t, "inbound", {
                    "doc_no": doc_no, "customer_id": cid, "in_date": head["in_date"],
                    "note": head["note"], "deleted": 0,
                    "created_at": head["created_at"]})
                self.r.add("进仓单")

            for src, payload in missing:
                data = dict(payload)
                data["inbound_id"] = target_inbound_id
                self.item[src["id"]] = _insert(self.t, "inbound_item", data)
                self.r.add("缸号")
                self.r.detail("进仓：%s / 缸号 %s / %s / %s卷 / %s米" %
                              (self._customer_name(cid), src["dye_lot"],
                               self._fabric_name(payload["fabric_id"]),
                               src["rolls"], src["meters"]))

    def _next_doc_no(self, table, prefix, on_date):
        day = str(on_date).replace("-", "")
        head = "%s-%s-" % (prefix, day)
        nums = []
        for row in self.t.execute(
                "SELECT doc_no FROM %s WHERE doc_no LIKE ?" % table, (head + "%",)):
            try:
                nums.append(int(row["doc_no"].rsplit("-", 1)[1]))
            except (ValueError, IndexError):
                pass
        return "%s%03d" % (head, (max(nums) if nums else 0) + 1)

    def _customer_name(self, cid):
        row = self.t.execute("SELECT name FROM customer WHERE id=?", (cid,)).fetchone()
        return row["name"] if row else str(cid)

    def _fabric_name(self, fid):
        if fid is None:
            return "未注明面料"
        row = self.t.execute("SELECT name FROM fabric WHERE id=?", (fid,)).fetchone()
        return row["name"] if row else str(fid)

    def _item_label(self, iid):
        if iid is None:
            return "无缸号"
        row = self.t.execute("SELECT dye_lot FROM inbound_item WHERE id=?", (iid,)).fetchone()
        return "缸号 " + row["dye_lot"] if row else "缸号ID %s" % iid

    # ---------- 卷码 ----------

    def _rolls(self):
        rows = self.s.execute("SELECT * FROM roll ORDER BY id").fetchall()
        for rr in rows:
            src = _dict(rr)
            iid = self.item.get(src["inbound_item_id"])
            if iid is None:
                self.r.conflict("卷码 #%s 找不到对应的缸号，不能合并。" % src["id"])
                continue
            tr = self.t.execute(
                "SELECT * FROM roll WHERE inbound_item_id=? AND seq=? ORDER BY id LIMIT 1",
                (iid, src["seq"])).fetchone()
            if tr is None:
                rid = _insert(self.t, "roll", {
                    "inbound_item_id": iid, "seq": src["seq"], "meters": src["meters"],
                    "shipment_item_id": None, "note": src["note"]})
                self.roll[src["id"]] = rid
                self.r.add("卷码")
            else:
                target = _dict(tr)
                self.roll[src["id"]] = target["id"]
                if _same(src, target, ("meters", "note")):
                    self.r.duplicate("卷码")
                else:
                    self.r.conflict("缸号对应卷号 %s 已存在，但米数或备注不同。" % src["seq"])

    # ---------- 加工 ----------

    def _productions(self):
        fields = ("customer_id", "inbound_item_id", "done_date", "process_id",
                  "fabric_id", "color", "rolls", "meters", "weight", "note",
                  "deleted", "created_at")
        for pr in self.s.execute(
                "SELECT * FROM production WHERE deleted=0 ORDER BY id"):
            src = _dict(pr)
            data = {
                "customer_id": self.customer[src["customer_id"]],
                "inbound_item_id": self.item.get(src["inbound_item_id"]),
                "done_date": src["done_date"],
                "process_id": self.process.get(src["process_id"]),
                "fabric_id": self.fabric.get(src["fabric_id"]),
                "color": src["color"], "rolls": src["rolls"],
                "meters": src["meters"], "weight": src["weight"],
                "note": src["note"], "deleted": 0,
                "created_at": src["created_at"],
            }
            if src["inbound_item_id"] is not None and data["inbound_item_id"] is None:
                self.r.conflict("加工记录 #%s 找不到对应缸号。" % src["id"])
                continue
            candidates = self._exact_rows("production", data, fields)
            target = next((x for x in candidates if x["id"] not in self._used_production),
                          None)
            if target:
                self.production[src["id"]] = target["id"]
                self._used_production.add(target["id"])
                self.r.duplicate("加工")
            else:
                pid = _insert(self.t, "production", data)
                self.production[src["id"]] = pid
                self._used_production.add(pid)
                self.r.add("加工")
                self.r.detail("加工：%s / %s / %s / %s卷 / %s米" %
                              (self._customer_name(data["customer_id"]),
                               self._item_label(data["inbound_item_id"]),
                               data["done_date"], data["rolls"], data["meters"]))

    def _exact_rows(self, table, data, fields):
        where = " AND ".join("%s IS ?" % f for f in fields)
        return [_dict(r) for r in self.t.execute(
            "SELECT * FROM %s WHERE %s ORDER BY id" % (table, where),
            _values(data, fields)).fetchall()]

    # ---------- 发货 ----------

    def _shipments(self):
        for sh in self.s.execute(
                "SELECT * FROM shipment WHERE deleted=0 ORDER BY id"):
            src_head = _dict(sh)
            head = {
                "customer_id": self.customer[src_head["customer_id"]],
                "ship_date": src_head["ship_date"], "receiver": src_head["receiver"],
                "plate_no": src_head["plate_no"], "note": src_head["note"],
                "deleted": 0, "created_at": src_head["created_at"],
            }
            src_items = []
            for si in self.s.execute(
                    "SELECT * FROM shipment_item WHERE shipment_id=? ORDER BY id",
                    (src_head["id"],)):
                raw = _dict(si)
                iid = self.item.get(raw["inbound_item_id"])
                pid = self.production.get(raw["production_id"])
                if raw["inbound_item_id"] is not None and iid is None:
                    self.r.conflict("发货单 %s 有一行找不到对应缸号。" % src_head["doc_no"])
                if raw["production_id"] is not None and pid is None:
                    self.r.conflict("发货单 %s 有一行找不到对应加工记录。" % src_head["doc_no"])
                data = {
                    "inbound_item_id": iid, "production_id": pid,
                    "fabric_id": self.fabric.get(raw["fabric_id"]),
                    "color": raw["color"],
                    "process_id": self.process.get(raw["process_id"]),
                    "rolls": raw["rolls"], "meters": raw["meters"],
                    "weight": raw["weight"], "unit_price": raw["unit_price"],
                    "amount": raw["amount"], "note": raw["note"],
                }
                src_items.append((raw["id"], data))

            matched = self._find_same_shipment(head, [x[1] for x in src_items])
            if matched:
                self._used_shipment.add(matched["id"])
                self.r.duplicate("发货单")
                self._map_existing_shipment_items(matched["id"], src_items)
                continue

            doc_no = src_head["doc_no"]
            if self.t.execute("SELECT 1 FROM shipment WHERE doc_no=?", (doc_no,)).fetchone():
                new_no = self._next_doc_no("shipment", "FH", head["ship_date"])
                self.r.renamed.append("发货单 %s → %s" % (doc_no, new_no))
                doc_no = new_no
            sid = _insert(self.t, "shipment", dict({"doc_no": doc_no}, **head))
            self._used_shipment.add(sid)
            self.r.add("发货单")
            self.r.detail("发货：%s / %s / 单号 %s / %d行 / 金额 %s" %
                          (self._customer_name(head["customer_id"]), head["ship_date"],
                           doc_no, len(src_items),
                           round(sum(float(x[1]["amount"] or 0) for x in src_items), 2)))
            for source_item_id, data in src_items:
                target_id = _insert(self.t, "shipment_item",
                                    dict({"shipment_id": sid}, **data))
                self.shipment_item[source_item_id] = target_id
                self.r.add("发货明细")

    def _shipment_item_signature(self, row):
        fields = ("inbound_item_id", "production_id", "fabric_id", "color",
                  "process_id", "rolls", "meters", "weight", "unit_price",
                  "amount", "note")
        return _values(row, fields)

    def _find_same_shipment(self, head, items):
        fields = ("customer_id", "ship_date", "receiver", "plate_no", "note",
                  "deleted", "created_at")
        candidates = self._exact_rows("shipment", head, fields)
        want = Counter(self._shipment_item_signature(x) for x in items)
        for cand in candidates:
            if cand["id"] in self._used_shipment:
                continue
            got = Counter(self._shipment_item_signature(_dict(x)) for x in self.t.execute(
                "SELECT * FROM shipment_item WHERE shipment_id=?", (cand["id"],)))
            if got == want:
                return cand
        return None

    def _map_existing_shipment_items(self, sid, source_items):
        buckets = defaultdict(list)
        for row in self.t.execute(
                "SELECT * FROM shipment_item WHERE shipment_id=? ORDER BY id", (sid,)):
            data = _dict(row)
            buckets[self._shipment_item_signature(data)].append(data["id"])
        used = Counter()
        for source_id, data in source_items:
            sig = self._shipment_item_signature(data)
            idx = used[sig]
            ids = buckets.get(sig, [])
            if idx >= len(ids):
                self.r.conflict("已存在的发货单明细无法一一对应，请人工检查。")
                continue
            self.shipment_item[source_id] = ids[idx]
            used[sig] += 1
            self.r.duplicate("发货明细")

    # ---------- 收款 ----------

    def _payments(self):
        fields = ("customer_id", "pay_date", "amount", "method", "ref_no", "note",
                  "deleted", "created_at")
        for pay in self.s.execute("SELECT * FROM payment WHERE deleted=0 ORDER BY id"):
            src = _dict(pay)
            data = {"customer_id": self.customer[src["customer_id"]],
                    "pay_date": src["pay_date"], "amount": src["amount"],
                    "method": src["method"], "ref_no": src["ref_no"],
                    "note": src["note"], "deleted": 0,
                    "created_at": src["created_at"]}
            candidates = self._exact_rows("payment", data, fields)
            target = next((x for x in candidates if x["id"] not in self._used_payment),
                          None)
            if target:
                self._used_payment.add(target["id"])
                self.r.duplicate("收款")
            else:
                rid = _insert(self.t, "payment", data)
                self._used_payment.add(rid)
                self.r.add("收款")
                self.r.detail("收款：%s / %s / %s元 / %s" %
                              (self._customer_name(data["customer_id"]),
                               data["pay_date"], data["amount"], data["method"]))

    # ---------- 卷码和发货行的最后一层关联 ----------

    def _link_rolls(self):
        for rr in self.s.execute(
                "SELECT * FROM roll WHERE shipment_item_id IS NOT NULL ORDER BY id"):
            src = _dict(rr)
            rid = self.roll.get(src["id"])
            target_si = self.shipment_item.get(src["shipment_item_id"])
            if rid is None or target_si is None:
                self.r.conflict("卷码 #%s 的发货关联无法对应。" % src["id"])
                continue
            current = self.t.execute(
                "SELECT shipment_item_id FROM roll WHERE id=?", (rid,)).fetchone()
            if current["shipment_item_id"] is None:
                self.t.execute("UPDATE roll SET shipment_item_id=? WHERE id=?",
                               (target_si, rid))
            elif current["shipment_item_id"] != target_si:
                self.r.conflict("卷码 #%s 已关联到另一条发货明细。" % src["id"])


def _simulate(source, target, source_path, fingerprint):
    memory = sqlite3.connect(":memory:")
    memory.row_factory = sqlite3.Row
    memory.execute("PRAGMA foreign_keys=ON")
    target.backup(memory)
    try:
        report = MergeReport(source_path, fingerprint)
        _Engine(source, memory, report).run()
        return report
    finally:
        memory.close()


def analyze_database(source_path):
    """只读预览。返回 MergeReport，不改服务器。"""
    source_path = os.path.abspath(source_path)
    fingerprint = _fingerprint(source_path)
    source = _open_source(source_path)
    try:
        from . import server
        with server.exclusive_local() as target:
            return _simulate(source, target, source_path, fingerprint)
    finally:
        source.close()


def merge_database(source_path, expected_key, expected_fingerprint):
    """确认并执行合并；预览之后任一边变化都会要求重新预览。"""
    if db.is_client():
        raise MergeError("只有管理数据的服务器电脑可以合并数据库。")
    source_path = os.path.abspath(source_path)
    fingerprint = _fingerprint(source_path)
    if fingerprint != expected_fingerprint:
        raise MergeError("来源数据库在预览后发生了变化，请重新选择并预览。")

    source = _open_source(source_path)
    try:
        from . import server
        with server.exclusive_local() as target:
            preview = _simulate(source, target, source_path, fingerprint)
            if preview.confirmation_key() != expected_key:
                raise MergeError("服务器数据在预览后发生了变化，请重新预览再确认。")
            if not preview.ok:
                raise MergeError("仍有数据冲突，不能合并。")

            backup_path = backup.backup_now("before_merge")
            try:
                target.execute("BEGIN IMMEDIATE")
                report = MergeReport(source_path, fingerprint)
                _Engine(source, target, report).run()
                if not report.ok:
                    raise MergeError("写入前复核发现冲突：%s" % "；".join(report.conflicts))
                if report.confirmation_key() != expected_key:
                    raise MergeError("写入计划与预览不一致，已取消。")
                target.execute(
                    """UPDATE app_setting SET value=CAST(CAST(value AS INTEGER)+1 AS TEXT)
                       WHERE key='data_rev'""")
                target.commit()
            except Exception:
                target.rollback()
                raise

        log_path = _write_log(report, backup_path)
        return MergeResult(report, backup_path, log_path)
    finally:
        source.close()


def _write_log(report, backup_path):
    os.makedirs(backup.BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(backup.BACKUP_DIR, "merge_%s.json" % stamp)
    payload = {
        "merged_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "backup_path": backup_path,
        "report": report.as_dict(),
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return path
    except OSError as e:
        report.warn("数据已合并，但日志文件写入失败：%s" % e)
        return ""
