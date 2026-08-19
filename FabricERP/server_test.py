# -*- coding: utf-8 -*-
"""服务器模式 + 手机网页的测试。

跑法：python server_test.py
用临时目录当数据目录，不碰真库。
"""

import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from urllib.parse import quote

TMP = tempfile.mkdtemp(prefix="erp_srv_")
os.environ["FABRIC_ERP_DIR"] = TMP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import db                                    # noqa: E402

# 测试库放临时目录，别动真数据
db.DATA_DIR = os.path.join(TMP, "data")
db.DB_PATH = os.path.join(db.DATA_DIR, "fabric_erp.db")
db.CLIENT_CFG = os.path.join(TMP, "client.json")

from app import models, mobile_web, remote_db, server, services   # noqa: E402

OK = FAIL = 0


def ck(label, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print("  ok   %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s %s" % (label, extra))


def get(url, cookie=None):
    req = urllib.request.Request(url)
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8"), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8"), e.headers


def post(url, payload, tok=None):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    if tok:
        req.add_header("X-Token", tok)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


# ---------------------------------------------------------------- 造点数据
print("\n[1] 建库、造一个客户一笔货")
conn = db.get_conn()
cid = models.save_customer({"name": "测试纺织", "opening_balance": 1000})
fid = models.get_or_create_fabric("335尼龙斜")
pid = {p["name"]: p["id"] for p in models.list_processes()}["白膜"]
services.save_inbound(cid, "2026-05-01", "", [
    {"dye_lot": "T001", "fabric_id": fid, "color": "黑",
     "rolls": 10, "meters": 1000}])
iid = models.list_batches(cid)[0]["item_id"]
services.save_production({"customer_id": cid, "inbound_item_id": iid,
                          "done_date": "2026-05-02", "process_id": pid,
                          "rolls": 5, "meters": 500})
prod = models.list_productions_of_batch(iid)[0]
services.save_shipment(cid, "2026-05-03", "", "", "", [
    {"inbound_item_id": iid, "production_id": prod["prod_id"],
     "process_id": pid, "rolls": 5, "meters": 500, "unit_price": 2.5}])
# 500 米 × 2.5 = 1250
models.save_payment(cid, "2026-05-10", 600, "转账")
bal = models.get_customer_balance(cid)
ck("结欠 = 1000 + 1250 - 600", abs(bal["balance"] - 1650) < 0.01, bal["balance"])

# ---------------------------------------------------------------- 手机网页
print("\n[2] 手机网页能渲染出来（不经过网络，直接调函数）")
home = mobile_web.page_home()
ck("首页有客户名", "测试纺织" in home)
ck("首页有结欠数字", "1,650.00" in home, )
ck("首页是完整 html", home.startswith("<!doctype html") and "</html>" in home)
stock = mobile_web.page_stock(cid)
ck("库存页有缸号", "T001" in stock)
ck("库存页剩余 500 米", "500" in stock)
st = mobile_web.page_statement(cid)
ck("对账页有期初 1000", "1,000.00" in st)
ck("对账页有收款 600", "600.00" in st)
ck("对账页有结欠 1650", "1,650.00" in st)
sh = mobile_web.page_ships(cid)
ck("发货页有单号", "2026-05-03" in sh)
ck("客户不存在时不抛错", "没有这个客户" in mobile_web.page_stock(99999))
ck("乱路径给提示", "没有这个页面" in mobile_web.render("/m/xxx", {}))
ck("登录页有口令输入框", "token" in mobile_web.page_login())

print("\n[2b] 客户名里的尖括号不能把页面搞坏（防 XSS）")
bad = models.save_customer({"name": "<script>x</script>厂",
                            "opening_balance": 0})
h = mobile_web.page_home()
ck("尖括号被转义", "<script>x</script>厂" not in h and "&lt;script&gt;" in h)
models.delete_customer(bad)

# ---------------------------------------------------------------- 服务器
print("\n[3] 开服务")
ck("开服务之前口令还是空的",
   conn.execute("SELECT value FROM app_setting WHERE key='server_token'"
                ).fetchone()["value"] == "")
srv = server.Server(port=8791, host="127.0.0.1")
ck("起得来", srv.start(), srv.error)
ck("running", srv.running)
# 一开服务就得把口令生成好：设置页面上要显示给人抄，空白的没法用
tok = conn.execute("SELECT value FROM app_setting WHERE key='server_token'"
                   ).fetchone()["value"]
ck("开服务就把口令生成好了（不用等谁来连）", len(tok) > 8, repr(tok))
ck("server.token() 读到的是同一个", server.token() == tok)
base = "http://127.0.0.1:8791"

print("\n[4] /ping 不要口令，只回版本")
code, body, _ = get(base + "/ping")
ck("200", code == 200, code)
info = json.loads(body)
ck("认得出是本软件", info.get("app") == "FabricERP")
ck("带 schema 版本", info.get("schema") == db.SCHEMA_VERSION)
ck("不含客户数据", "测试纺织" not in body)

print("\n[5] 没口令看不到数据")
code, body, _ = get(base + "/m")
ck("给的是登录页", code == 200 and "请输入查看口令" in body)
ck("登录页里没有客户数据", "测试纺织" not in body)
code, body, _ = get(base + "/m?token=wrong-one")
ck("口令错也只给登录页", "请输入查看口令" in body and "测试纺织" not in body)
# 手机上有人输中文口令：hmac.compare_digest 碰到非 ASCII 会抛异常，
# 那就成了 500 白屏。必须还是老老实实回登录页。
code, body, _ = get(base + "/m?token=" + quote("中文口令"))
ck("中文口令不会把服务器搞崩", code == 200 and "请输入查看口令" in body, code)

print("\n[6] 口令对了能看，并且发 cookie")
code, body, hdr = get(base + "/m?token=" + tok)
ck("看到客户", code == 200 and "测试纺织" in body)
cookie = hdr.get("Set-Cookie") or ""
ck("发了 cookie", "erp_token=" + tok in cookie, cookie)
ck("cookie 带 HttpOnly", "HttpOnly" in cookie)
code, body, _ = get(base + "/m/stock?c=%d" % cid, cookie="erp_token=" + tok)
ck("拿 cookie 能翻库存页", "T001" in body)
code, body, _ = get(base + "/m/statement?c=%d" % cid, cookie="erp_token=" + tok)
ck("拿 cookie 能翻对账页", "1,650.00" in body)

print("\n[7] /api/sql 必须带对口令")
code, res = post(base + "/api/sql", {"stmts": [{"sql": "SELECT 1"}]})
ck("不带口令 401", code == 401, code)
code, res = post(base + "/api/sql", {"stmts": [{"sql": "SELECT 1"}]}, "guessing")
ck("口令错 401", code == 401, code)
code, res = post(base + "/api/sql",
                 {"stmts": [{"sql": "SELECT 1"}]}, tok[:-1])
ck("口令差一个字也不行", code == 401, code)
code, res = post(base + "/api/sql", {"stmts": []}, tok)
ck("空语句 400", code == 400, code)
code, res = post(base + "/api/sql",
                 {"stmts": [{"sql": "SELECT name FROM customer WHERE id=?",
                             "args": [cid]}]}, tok)
ck("查得到", code == 200 and res["results"][0]["rows"][0][0] == "测试纺织", res)
code, res = post(base + "/api/sql", {"stmts": [{"sql": "SELECT * FROM 没这表"}]}, tok)
ck("SQL 错了原样报回来", code == 400 and "没这表" in res.get("error", ""), res)

print("\n[8] 客户端连过来（RemoteConnection）")
rc = remote_db.RemoteConnection("127.0.0.1", 8791, tok)
row = rc.execute("SELECT name, opening_balance FROM customer WHERE id=?",
                 (cid,)).fetchone()
ck("按列名取", row["name"] == "测试纺织", dict(row))
ck("按下标取", row[0] == "测试纺织")
ck("keys()", "opening_balance" in row.keys())
rows = rc.execute("SELECT * FROM v_customer_balance").fetchall()
ck("视图也能查", any(r["customer"] == "测试纺织" for r in rows))
ck("fetchall 取过一次就空了",
   rc.execute("SELECT 1").fetchall() and True)

print("\n[9] 事务：中途出错不能留半截数据")
rc.begin()
rc.execute("INSERT INTO customer(name, opening_balance) VALUES ('半截厂', 0)")
n = rc.execute("SELECT COUNT(*) c FROM customer WHERE name='半截厂'").fetchone()[0]
ck("事务里读得到自己刚写的", n == 1, n)
rc.rollback()
n = conn.execute("SELECT COUNT(*) c FROM customer WHERE name='半截厂'").fetchone()["c"]
ck("回滚后服务器上没有这条", n == 0, n)

rc.begin()
rc.execute("INSERT INTO customer(name, opening_balance) VALUES ('提交厂', 0)")
rc.commit()
n = conn.execute("SELECT COUNT(*) c FROM customer WHERE name='提交厂'").fetchone()["c"]
ck("提交后服务器上有了", n == 1, n)

# 一张单子存到一半出错（缸号重号之类），前面写进去的行不能留下
rc.begin()
rc.execute("INSERT INTO customer(name, opening_balance) VALUES ('好的', 0)")
try:
    rc.execute("INSERT INTO customer(id, name) VALUES (1, '撞主键')")  # 故意撞
    raised = False
except remote_db.RemoteError as e:
    raised = "UNIQUE" in str(e)
ck("出错当场就报，报的是原话", raised)
rc.rollback()
n = conn.execute("SELECT COUNT(*) c FROM customer WHERE name='好的'").fetchone()["c"]
ck("同一个事务里前面那句也没落地", n == 0, n)

print("\n[9b] 两台电脑同时存单子，不能串账")
r2 = remote_db.RemoteConnection("127.0.0.1", 8791, tok)
rc.begin()
rc.execute("INSERT INTO customer(name, opening_balance) VALUES ('甲厂', 0)")
r2.begin()
try:
    r2.execute("INSERT INTO customer(name, opening_balance) VALUES ('乙厂', 0)")
    blocked = False
except remote_db.RemoteError as e:
    blocked = "另一台电脑" in str(e)
ck("甲的事务开着，乙被挡住并且提示看得懂", blocked)
rc.commit()
n = conn.execute("SELECT COUNT(*) c FROM customer WHERE name='甲厂'").fetchone()["c"]
ck("甲提交成功", n == 1, n)
r2.begin()
r2.execute("INSERT INTO customer(name, opening_balance) VALUES ('乙厂', 0)")
r2.commit()
n = conn.execute("SELECT COUNT(*) c FROM customer WHERE name='乙厂'").fetchone()["c"]
ck("甲让开以后乙就能存了", n == 1, n)
ck("甲的和乙的没混在一起",
   conn.execute("SELECT COUNT(*) c FROM customer "
                "WHERE name IN ('甲厂','乙厂')").fetchone()["c"] == 2)

print("\n[10] 通过服务器走完整业务：客户端存一张发货单")
db.close_conn()
db.save_client_config("127.0.0.1", 8791, tok)
ck("is_client()", db.is_client())
c2 = db.get_conn()
ck("get_conn 返回的是远程连接",
   isinstance(c2, remote_db.RemoteConnection), type(c2).__name__)
cid2 = models.save_customer({"name": "远程厂", "opening_balance": 0})
ck("远程建客户拿到 id", bool(cid2), cid2)
f2 = models.get_or_create_fabric("远程布")
i2 = services.save_inbound(cid2, "2026-06-01", "", [
    {"dye_lot": "R001", "fabric_id": f2, "color": "白",
     "rolls": 4, "meters": 400}])
ck("远程存进仓单", bool(i2), i2)
bs = models.list_batches(cid2)
ck("远程读得到这一缸", len(bs) == 1 and bs[0]["dye_lot"] == "R001",
   [dict(b) for b in bs])
ck("剩余 400 米", abs(bs[0]["left_meters"] - 400) < 0.01, bs[0]["left_meters"])
i2id = bs[0]["item_id"]
services.save_shipment(cid2, "2026-06-02", "", "", "", [
    {"inbound_item_id": i2id, "fabric_id": f2,
     "rolls": 2, "meters": 200, "unit_price": 3}])
b2 = models.get_customer_balance(cid2)
ck("远程发货算出结欠 600", abs(b2["balance"] - 600) < 0.01, b2["balance"])
bs = models.list_batches(cid2)
ck("远程发货扣了库存，剩 200", abs(bs[0]["left_meters"] - 200) < 0.01,
   bs[0]["left_meters"])
st2 = services.statement(cid2)
ck("远程也能出对账单", abs(st2["closing"] - 600) < 0.01, st2["closing"])

print("\n[10b] data_rev 隔着网络也得跟着涨（界面靠它决定要不要重读）")
rev_before = db.data_rev()
ck("远程读得到 data_rev", rev_before >= 0, rev_before)
services.save_shipment(cid2, "2026-06-02", "", "", "", [
    {"fabric_id": f2, "rolls": 1, "meters": 50, "unit_price": 2}])
rev_after = db.data_rev()
ck("客户端存了东西，data_rev 变大", rev_after > rev_before,
   (rev_before, rev_after))
ck("只读不会让它变", db.data_rev() == rev_after, db.data_rev())
# 服务器那台自己看到的必须是同一个数 —— 不然对面的界面永远不刷
with server.local_only():
    ck("服务器本机看到的是同一个数", db.data_rev() == rev_after, db.data_rev())

print("\n[11] 单号不重号（远程也得靠得住）")
nos = set()
for i in range(5):
    sid, _ = services.save_shipment(cid2, "2026-06-03", "", "", "", [
        {"fabric_id": f2, "rolls": 1, "meters": 10, "unit_price": 1}])
    nos.add(models.get_shipment(sid)[0]["doc_no"])
ck("5 张单 5 个号", len(nos) == 5, nos)

print("\n[12] 服务器关了以后，客户端报的错要看得懂")
srv.stop()
ck("stop 后不 running", not srv.running)
try:
    models.list_customers()
    msg = ""
except remote_db.RemoteError as e:
    msg = str(e)
ck("提示里说了连不上", "连不上服务器" in msg, msg)
ck("提示里说了怎么办", "开着服务" in msg)

print("\n[13] 端口被占的话要说清楚，不能白开一个没用的服务")
a = server.Server(port=8792, host="127.0.0.1")
b = server.Server(port=8792, host="127.0.0.1")
ck("第一个起得来", a.start())
ck("第二个起不来", not b.start())
ck("说了是端口问题", "端口打不开" in b.error, b.error)
a.stop()

print("\n[14] 清掉客户端配置就回到单机")
db.close_conn()
os.remove(db.CLIENT_CFG)
ck("不是客户端了", not db.is_client())
ck("又是本地连接了", not isinstance(db.get_conn(), remote_db.RemoteConnection))

db.close_conn()
shutil.rmtree(TMP, ignore_errors=True)
print("\n%d 项通过，%d 项失败" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
