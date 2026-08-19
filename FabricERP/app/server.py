# -*- coding: utf-8 -*-
"""服务器模式：这台电脑开一个服务，别的电脑和手机连过来。

为什么这么做
------------
SQLite 本身不能让两台电脑同时开着写（放共享文件夹里迟早写坏库）。所以改成
**一台电脑管库，别人通过它读写**：

    你的电脑（服务器）          会计的电脑            手机
    ├ 数据库 fabric_erp.db      软件连过来              浏览器打开网页
    └ 开着这个服务              增删改查都走网络        只看，不改

好处是业务代码一行都不用改 —— 客户端那边把 SQL 发过来，服务器在自己的库上
执行完把结果发回去（见 remote_db.py）。加锁、事务、备份都还在服务器这一边，
只有一个进程碰数据库文件，不会写坏。

安全
----
`/api/` 全部要口令（首次启动自动生成，在「设置」里能看到）。
手机网页 `/m/` 也要口令，登录一次记在 cookie 里。
只在局域网和 Tailscale 里用，**不要往公网上转发端口**。
"""

import hashlib
import hmac
import json
import os
import secrets
import socket
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import db, mobile_web, version

DEFAULT_PORT = 8756

# 当前 exe 的信息（大小 + sha256），给「会计那台自动更新」用。
_EXE_CACHE = {}


def exe_info():
    """当前运行的这个程序文件的信息；开发模式（没打包）返回 None。

    只算一次 sha256 并缓存 —— exe 运行中不会变，每次请求都重读没意义。
    """
    if "info" in _EXE_CACHE:
        return _EXE_CACHE["info"]
    info = None
    if getattr(sys, "frozen", False):
        exe = sys.executable
        try:
            size = os.path.getsize(exe)
            h = hashlib.sha256()
            with open(exe, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            info = {"size": size, "sha256": h.hexdigest()}
        except OSError:
            info = None
    _EXE_CACHE["info"] = info
    return info



# 写操作要排队：SQLite 同一时刻只能有一个写事务。用一把大锁最简单也最稳，
# 反正就两三个人用，锁的代价可以忽略。
_LOCK = threading.RLock()

# 当前谁的事务开着（客户端每次启动生成一个 session 号）。同一时刻只允许一个 ——
# 见 _sql() 里的说明。
_TX = {}
TX_TIMEOUT = 30          # 那台电脑半路崩了，超过这么久就把它的事务扔掉


@contextmanager
def local_only():
    """这一段里的 models / services 都读本机的库。

    手机网页是靠 models 取数的，而 models 走 db.get_conn()。这台电脑万一
    也配成了客户端，那就绕回自己了（见 _setting 的说明）。所以处理请求期间
    把连接临时换成本地的，出去再换回来。
    """
    old = db._conn
    db._conn = db.local_conn()
    try:
        yield
    finally:
        db._conn = old


@contextmanager
def exclusive_local():
    """独占本机数据库，供备份恢复、账套合并这类整库操作使用。

    普通客户端请求也使用 ``_LOCK``。持有这把锁期间不会有网络写入插进来；
    如果某个客户端事务还没提交，则明确拒绝整库操作，不能把半张单据混进去。
    """
    with _LOCK, local_only():
        busy = _TX.get("session")
        if busy:
            if time.time() - _TX.get("since", 0) > TX_TIMEOUT:
                db.local_conn().rollback()
                _TX.clear()
            else:
                raise RuntimeError("另一台电脑正在保存，请过几秒再试。")
        yield db.local_conn()


def _setting(key, default=""):
    """读设置，**只读本机的库**。

    不能用 db.get_setting：这台电脑要是也配了客户端模式，那句查询会绕到
    网络上去 —— 而它恰好是在处理别人的请求时调的，等于自己请求自己，
    一层套一层直到超时。口令这种东西必须就地读。
    """
    row = db.local_conn().execute(
        "SELECT value FROM app_setting WHERE key=?", (key,)).fetchone()
    return row["value"] if row and row["value"] not in (None, "") else default


def _set_setting(key, value):
    conn = db.local_conn()
    conn.execute("INSERT INTO app_setting(key,value) VALUES (?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, str(value)))
    conn.commit()


def token():
    """服务器口令。第一次启动自动生成一串，之后一直用它。"""
    t = _setting("server_token", "")
    if not t:
        t = secrets.token_urlsafe(12)
        _set_setting("server_token", t)
    return t


def same_token(got, want):
    """比口令。用 compare_digest 是为了不给人逐字符试出来的机会。

    先编成 bytes：compare_digest 遇到非 ASCII 的字符串会直接抛异常 ——
    手机上要是有人输了个中文口令，那就变成 500 白屏，而不是「口令不对」。
    """
    if not got or not want:
        return False
    return hmac.compare_digest(str(got).encode("utf-8", "replace"),
                               str(want).encode("utf-8", "replace"))


def lan_ip():
    """本机在局域网里的地址 —— 告诉别人往哪儿连。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))     # 不会真的发包，只为拿到出口网卡
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "FabricERP"

    # ---------- 基础 ----------

    def log_message(self, fmt, *args):
        pass            # 不往控制台刷日志，打包成 windowed exe 后没地方输出

    def _ok(self, body, ctype="application/json; charset=utf-8", cookie=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def _fail(self, code, msg):
        data = json.dumps({"error": msg}, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authed(self):
        """口令对不对。请求头、查询串、cookie 三个地方都认。"""
        got = (self.headers.get("X-Token")
               or parse_qs(urlparse(self.path).query).get("token", [""])[0]
               or self._cookie_token())
        return same_token(got, token())

    def _cookie_token(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "erp_token":
                return v
        return ""

    # ---------- 路由 ----------

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/ping":
            # 客户端拿它探活、比版本，不需要口令（只回版本，不含数据）
            info = {"ok": True, "app": "FabricERP",
                    "schema": db.SCHEMA_VERSION,
                    "version_name": version.VERSION_NAME,
                    "version_code": version.VERSION_CODE,
                    "build": version.BUILD_STAMP}
            exe = exe_info()
            if exe:
                info["exe_size"] = exe["size"]
                info["exe_sha256"] = exe["sha256"]
            return self._ok(json.dumps(info))
        if path == "/update/download":
            # 给会计那台下载新程序。要口令，免得局域网里谁都能把 exe 拉走。
            if not self._authed():
                return self._fail(401, "口令不对")
            return self._send_exe()
        if path.startswith("/m") or path == "/":
            return self._mobile(path)
        return self._fail(404, "没有这个地址")

    def _send_exe(self):
        """把正在运行的这个 exe 原样发出去，供客户端下载更新。"""
        exe = exe_info()
        if not exe:
            return self._fail(404, "开发模式没有可下载的程序文件")
        path = sys.executable
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(exe["size"]))
        self.end_headers()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._authed():
            return self._fail(401, "口令不对")
        if path == "/api/sql":
            return self._sql()
        return self._fail(404, "没有这个地址")

    # ---------- 手机网页 ----------

    def _mobile(self, path):
        q = parse_qs(urlparse(self.path).query)
        if not self._authed():
            return self._ok(mobile_web.page_login(),
                            ctype="text/html; charset=utf-8")

        # 口令是从网址里带进来的（扫码或者点链接），就顺手存成 cookie ——
        # 页面里的「库存 / 对账」链接不带口令，不存的话点一下就又要重新输。
        cookie = None
        if not same_token(self._cookie_token(), token()):
            tk = q.get("token", [""])[0]
            if same_token(tk, token()):
                cookie = ("erp_token=%s; Path=/; Max-Age=2592000; "
                          "HttpOnly; SameSite=Lax" % tk)

        with _LOCK, local_only():
            try:
                html = mobile_web.render(path, q)
            except Exception as e:
                html = mobile_web.page_error(str(e))
        return self._ok(html, ctype="text/html; charset=utf-8", cookie=cookie)

    # ---------- 给别的电脑执行 SQL ----------

    def _sql(self):
        """客户端把 SQL 发过来，在服务器的库上跑完返回结果。

        客户端那边是把 sqlite3 的 execute 转发过来的，所以这里只做转发，
        不做业务判断 —— 业务校验在客户端的 services 层已经做过了。
        """
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            return self._fail(400, "请求格式不对：%s" % e)

        stmts = req.get("stmts")
        if not isinstance(stmts, list):
            return self._fail(400, "请求里没有 stmts")
        done = bool(req.get("commit") or req.get("rollback"))
        if not stmts and not done:
            return self._fail(400, "没有要执行的语句")

        sess = str(req.get("session") or "")
        with _LOCK:
            conn = db.local_conn()

            # 谁的事务开着，就只让谁继续。不然会串账：A 存单子存到一半
            # （写已经发过来了但还没提交），B 一提交，把 A 的半截数据一起
            # 提交进去了 —— 这种账错了根本查不出来。
            busy = _TX.get("session")
            if busy and busy != sess:
                if time.time() - _TX.get("since", 0) > TX_TIMEOUT:
                    conn.rollback()          # 那台电脑大概是崩了/断网了
                    _TX.clear()
                else:
                    return self._fail(409, "另一台电脑正在保存，请过几秒再试。")

            if req.get("rollback"):
                conn.rollback()
                _TX.clear()
                return self._ok(json.dumps({"results": []}))

            out = []
            try:
                for st in stmts:
                    cur = conn.execute(st.get("sql") or "", st.get("args") or [])
                    if cur.description:      # 查询：把行发回去
                        cols = [c[0] for c in cur.description]
                        out.append({"cols": cols,
                                    "rows": [list(r) for r in cur.fetchall()]})
                    else:                    # 写：回受影响行数和新 id
                        out.append({"rowcount": cur.rowcount,
                                    "lastrowid": cur.lastrowid})
            except Exception as e:
                conn.rollback()
                _TX.clear()
                return self._fail(400, "%s: %s" % (type(e).__name__, e))

            if req.get("commit"):
                conn.commit()
                _TX.clear()
            else:
                # 写已经落到库里但还没提交 —— 记下是谁的，别人先等着
                _TX["session"], _TX["since"] = sess, time.time()
        return self._ok(json.dumps({"results": out}, ensure_ascii=False,
                                   default=str))


class _HTTPServer(ThreadingHTTPServer):
    # 标准库默认 allow_reuse_address = 1。在 Windows 上这一条会允许**两个进程
    # 绑同一个端口**，谁都不报错，连接被随机分给其中一个 —— 等于开了两台服务器
    # 各管一半，账必然乱。所以关掉，端口被占就明确失败。
    allow_reuse_address = False
    daemon_threads = True


class Server:
    """服务器的开关。放在后台线程里跑，不挡着界面。"""

    def __init__(self, port=None, host="0.0.0.0"):
        self.port = int(port or _setting("server_port", DEFAULT_PORT))
        self.host = host
        self.httpd = None
        self.thread = None
        self.error = ""

    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive())

    def start(self):
        if self.running:
            return True
        token()          # 先把口令生成好 —— 设置页面上要显示，不能是空的
        try:
            self.httpd = _HTTPServer((self.host, self.port), Handler)
        except OSError as e:
            # 最常见就是端口被占（软件开了两遍，或者别的程序在用这个口）
            self.error = ("%s 端口打不开：%s\n"
                          "多半是这个软件已经开着了，或者换个端口号试试。"
                          % (self.port, e))
            return False
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       kwargs={"poll_interval": 0.3},
                                       daemon=True)
        self.thread.start()
        self.error = ""
        return True

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        self.thread = None

    @property
    def urls(self):
        """给人看的地址：电脑填前一个，手机浏览器开后一个。"""
        ip = lan_ip()
        return {
            "client": "%s:%d" % (ip, self.port),
            "mobile": "http://%s:%d/m?token=%s" % (ip, self.port, token()),
        }


_server = None


def instance():
    global _server
    if _server is None:
        _server = Server()
    return _server


def autostart():
    """设置里勾了「开机就开服务」的话，启动时自动开。"""
    if db.is_client():
        # 自己就是客户端，库在别人那儿 —— 再开服务只会把请求转来转去
        return None
    if _setting("server_enabled", "0") == "1":
        s = instance()
        s.start()
        return s
    return None
