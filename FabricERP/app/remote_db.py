# -*- coding: utf-8 -*-
"""客户端：把数据库操作发给服务器执行。

整个软件的数据访问都走 `db.get_conn()` 和 `db.transaction()`。所以要让会计那台
电脑连过来，最省事的办法不是改几十处业务代码，而是**换掉那个连接对象** ——
这里做一个长得跟 sqlite3.Connection 一样的东西（execute / executemany /
commit / rollback / row_factory），它把 SQL 发给服务器跑。

事务怎么办
----------
`transaction()` 里的每一句照样立刻发给服务器，只是**先不提交** —— 服务器
把这些写攒在它自己的事务里，等收到 commit 才落地，出错就 rollback。
所以「一张单子要么整张存上，要么一行都不留」这条还是成立的。

为什么不在客户端攒成一批再发：业务代码到处要 `lastrowid`（存了单头才能
挂明细），不发就拿不到 id。局域网一个来回一两毫秒，多几个来回不值得省。

同一时刻只允许一台电脑开着事务，服务器那边靠 session 号认人（见 server.py）。
"""

import json
import secrets
import sqlite3
import threading
import urllib.error
import urllib.request

TIMEOUT = 20


class RemoteError(Exception):
    """服务器那边报的错。原样带回来，界面上照样能提示「缸号已存在」这种。"""


class Row(sqlite3.Row):
    pass


class _Cursor:
    """只实现用得到的那几样：fetchone / fetchall / lastrowid / rowcount。"""

    def __init__(self, result, factory):
        self._rows = []
        self.lastrowid = result.get("lastrowid")
        self.rowcount = result.get("rowcount", -1)
        self.description = None
        if "cols" in result:
            cols = result["cols"]
            self.description = [(c,) + (None,) * 6 for c in cols]
            self._rows = [factory(cols, r) for r in result["rows"]]
        self._i = 0

    def fetchone(self):
        if self._i >= len(self._rows):
            return None
        self._i += 1
        return self._rows[self._i - 1]

    def fetchall(self):
        out = self._rows[self._i:]
        self._i = len(self._rows)
        return out

    def __iter__(self):
        return iter(self.fetchall())


class _DictRow(dict):
    """服务器发回来的是列表，包成能按列名取、也能按下标取的东西 ——
    业务代码里 row["dye_lot"] 和 row[0] 两种写法都有。"""

    def __init__(self, cols, values):
        super().__init__(zip(cols, values))
        self._values = list(values)

    def __getitem__(self, k):
        if isinstance(k, int):
            return self._values[k]
        return super().__getitem__(k)

    def keys(self):
        return list(super().keys())


class RemoteConnection:
    """假装是个数据库连接，其实是往服务器发请求。"""

    def __init__(self, host, port, token):
        self.base = "http://%s:%d" % (host, int(port))
        self.token = token
        self.row_factory = None          # 摆着好看，业务代码会设它
        self._in_tx = False
        self._sent = False               # 这个事务里有没有已经发出去的写
        self._lock = threading.RLock()
        # 认人用的号：服务器靠它分清「事务是谁开的」，别把两台电脑的写搅在一起
        self.session = secrets.token_hex(8)

    # ---------- 网络 ----------

    def _post(self, stmts, commit=False, rollback=False):
        body = json.dumps({"stmts": stmts, "commit": commit,
                           "rollback": rollback,
                           "session": self.session}).encode("utf-8")
        req = urllib.request.Request(
            self.base + "/api/sql", data=body,
            headers={"Content-Type": "application/json", "X-Token": self.token})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8"))["results"]
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("error", str(e))
            except Exception:
                msg = str(e)
            raise RemoteError(msg)
        except urllib.error.URLError as e:
            raise RemoteError("连不上服务器（%s）：%s\n"
                              "请确认那台电脑开着软件、开着服务，"
                              "并且两台电脑在同一个网里。" % (self.base, e.reason))

    # ---------- 假装是 sqlite3.Connection ----------

    def execute(self, sql, args=()):
        """一句一句发过去，事务里也照发 —— 只是不提交。

        为什么不攒起来一次发（本来是那么写的）：业务代码到处都要 `lastrowid`，
        比如存进仓单要先拿到单号 id 才能挂明细。攒着不发就拿不到 id，
        返回 None，接着明细的 customer_id 就是空的，直接报错。
        所以宁可多几个来回 —— 局域网里一个来回一两毫秒，无所谓。
        """
        with self._lock:
            res = self._post([{"sql": sql, "args": list(args)}],
                             commit=not self._in_tx)
            if self._in_tx:
                self._sent = True        # 服务器那边事务开着了，回滚要通知它
            return _Cursor(res[0] if res else {}, self._mk)

    def executemany(self, sql, seq):
        with self._lock:
            stmts = [{"sql": sql, "args": list(a)} for a in seq]
            if not stmts:
                return _Cursor({"rowcount": 0}, self._mk)
            self._post(stmts, commit=not self._in_tx)
            if self._in_tx:
                self._sent = True
            return _Cursor({"rowcount": len(stmts)}, self._mk)

    def executescript(self, sql):
        # 建表建视图用的，客户端不需要 —— 库在服务器那边，早就建好了
        return _Cursor({"rowcount": 0}, self._mk)

    def _mk(self, cols, values):
        return _DictRow(cols, values)

    def commit(self):
        with self._lock:
            if self._sent:
                self._post([], commit=True)
                self._sent = False
            self._in_tx = False

    def rollback(self):
        with self._lock:
            if self._sent:
                # 已经发过去的那些，服务器那边还在事务里挂着 —— 不告诉它撤，
                # 下一个人一提交就把这半截数据一起提交进去了。
                try:
                    self._post([], rollback=True)
                except RemoteError:
                    pass                 # 连不上就算了，服务器超时会自己清
                self._sent = False
            self._in_tx = False

    def begin(self):
        with self._lock:
            self._in_tx = True
            self._sent = False

    def close(self):
        pass

    def cursor(self):
        return self


def check(host, port, token):
    """测试连接。返回 (通不通, 说明)。"""
    url = "http://%s:%d/ping" % (host, int(port))
    try:
        with urllib.request.urlopen(url, timeout=6) as r:
            info = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return False, "连不上 %s：%s" % (url, e)
    if info.get("app") != "FabricERP":
        return False, "%s 上跑的不是本软件" % url
    # 口令对不对，拿一句最轻的查询试
    try:
        RemoteConnection(host, port, token).execute("SELECT 1").fetchone()
    except RemoteError as e:
        return False, str(e)
    if info.get("schema") != 2:
        return True, "连上了，但服务器的数据库版本是 %s，本机是 2 —— " \
                     "两边最好装同一个版本的软件。" % info.get("schema")
    return True, "连上了。"
