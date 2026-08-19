# -*- coding: utf-8 -*-
"""把老账本解析出来的东西写进数据库。

规矩两条，都是为了出了事能查、能重来：
  1. **一律走 services**，不自己拼 SQL —— 超发、缸号重号、金额计算这些校验
     跟手工录入走同一条路，导进去的数据和手敲的没有区别。
  2. **导入前自动备份数据库**，并且每张单子都写上「来源：账本 X 表 第N行」。
     导错了可以照着备份还原，也能拿着行号回去翻账本。

调用顺序（不能乱）：客户 → 面料/工艺 → 价格 → 进仓 → 加工 → 发货 → 收款。
发货要挂到缸号上，所以必须等进仓写完拿到 inbound_item.id。
"""
import os
import shutil
import time

from . import db, models, services

SRC_TAG = "老账本导入"


class CommitReport:
    """导入结果：进去多少、跳过多少、哪几行有问题。"""

    def __init__(self):
        self.counts = {}
        self.skipped = []        # [(什么, 原因)]
        self.warnings = []
        self.backup = ""

    def add(self, kind, n=1):
        self.counts[kind] = self.counts.get(kind, 0) + n

    def skip(self, what, why):
        self.skipped.append((what, why))

    def warn(self, msg):
        self.warnings.append(msg)

    @property
    def summary(self):
        got = "、".join("%s %d" % (k, v) for k, v in self.counts.items() if v)
        s = "导入完成：" + (got or "没有可导入的数据")
        if self.skipped:
            s += "；跳过 %d 条" % len(self.skipped)
        return s


def backup_db():
    """导入前备份。文件名带时间戳，不覆盖旧的。"""
    path = db.DB_PATH
    if not os.path.exists(path):
        return ""
    dst = "%s.导入前备份-%s.db" % (os.path.splitext(path)[0],
                                  time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(path, dst)
    return dst


def _src(item):
    """「账本 4月份 第77行」—— 出问题能直接翻回去对。"""
    sheet, row = item.get("sheet"), item.get("row")
    if not sheet:
        return SRC_TAG
    return "%s：%s%s" % (SRC_TAG, sheet, ("第%d行" % row) if row else "")


def _note(item, extra=""):
    parts = [x for x in (item.get("note"), extra, _src(item)) if x]
    return "；".join(parts)


def ensure_customer(name, use_dye_lot=True, track_weight=False,
                    opening_balance=None, opening_date=None):
    """找客户，没有就建。已存在的不动它的设置 —— 别把人家改过的配置冲掉。"""
    for c in models.list_customers(name):
        # v_customer_balance 里客户名那列叫 customer
        if c["customer"] == name:
            return c["customer_id"], False
    return models.save_customer({
        "name": name, "use_dye_lot": int(bool(use_dye_lot)),
        "track_weight": int(bool(track_weight)),
        "opening_balance": opening_balance or 0,
        "opening_date": opening_date,
        "note": SRC_TAG}), True


def _process_id(name, cache):
    """工艺按名字建档。空的返回 None（有些账本没写加工方式）。"""
    name = (name or "").strip()
    if not name:
        return None
    if name not in cache:
        hit = [p for p in models.list_processes() if p["name"] == name]
        cache[name] = hit[0]["id"] if hit else models.save_process(name)
    return cache[name]


def _fabric_id(name, cache):
    name = (name or "").strip() or "未注明"
    if name not in cache:
        cache[name] = models.get_or_create_fabric(name)
    return cache[name]


def commit(result, customer_name=None, dry_run=False, prod_ids=None):
    """把一个 ParseResult 写进库。dry_run=True 只统计不写。

    prod_ids: {加工key: production_id}。鹏川的加工在「入库明细」里、发货在
    「对账明细」里，是两个文件两次 commit —— 第一次导加工时把 id 攒在这个
    字典里，第二次导发货时用它把发货挂到成品上。同一个字典传两次就行。

    返回 CommitReport。
    """
    rep = CommitReport()
    name = customer_name or result.customer
    if dry_run:
        for k, v in result.stats.items():
            rep.add(k, v)
        return rep

    rep.backup = backup_db()
    cid, created = ensure_customer(
        name, use_dye_lot=result.use_dye_lot,
        opening_balance=result.opening_debt,
        opening_date=getattr(result, "opening_date", None))
    if created:
        rep.add("新建客户")
    if result.opening_debt and not created:
        # 客户已存在（比如龚松权的入库表先导过一次，那次还不知道期初欠款）。
        # 原来是 0 就补上；已经有数了就不动，只提醒 —— 别把人家改过的数冲掉。
        cur = models.get_customer(cid)
        if not (cur and cur["opening_balance"]):
            data = dict(cur)          # sqlite3.Row 要先转成 dict 才能改
            data["opening_balance"] = result.opening_debt
            data.setdefault("opening_date", None)
            models.save_customer(data, cid)
            rep.add("期初欠款")
            rep.warn("已把期初欠款 %s 元记到客户「%s」上（来源：%s）。"
                     % (result.opening_debt, name, result.opening_note))
        else:
            rep.warn("账本里有期初欠款 %s 元（%s），但客户「%s」已经填过期初余额"
                     "%s 元了 —— 没有覆盖，请到客户资料里手工确认。"
                     % (result.opening_debt, result.opening_note, name,
                        cur["opening_balance"]))

    fab, proc = {}, {}
    _commit_prices(result, cid, fab, proc, rep)
    lots = _commit_inbounds(result, cid, fab, rep)
    prods = _commit_productions(result, cid, fab, proc, lots, rep, prod_ids)
    _commit_shipments(result, cid, fab, proc, lots, rep, prods)
    _commit_payments(result, cid, rep)
    return rep


def _commit_prices(result, cid, fab, proc, rep):
    for p in result.prices:
        try:
            models.save_price(cid, _fabric_id(p.get("fabric"), fab),
                              _process_id(p.get("process"), proc),
                              float(p["unit_price"]),
                              p.get("effective_date") or "2000-01-01",
                              note=_src(p))
            rep.add("价格")
        except Exception as e:
            rep.skip("价格 %s" % p.get("fabric"), str(e))


def _commit_inbounds(result, cid, fab, rep):
    """进仓按日期归单：同一天的并成一张进仓单，跟手工录入的习惯一致。

    返回 {缸号: inbound_item_id}，发货要用它挂缸。
    """
    lots = {}
    by_date = {}
    for x in result.inbounds:
        by_date.setdefault(x["in_date"], []).append(x)

    for d in sorted(by_date):
        rows = by_date[d]
        items = [{"dye_lot": x["dye_lot"], "fabric_id": _fabric_id(x.get("fabric"), fab),
                  "color": x.get("color") or "", "rolls": int(x.get("rolls") or 0),
                  "meters": float(x.get("meters") or 0), "note": _note(x)}
                 for x in rows]
        try:
            iid = services.save_inbound(cid, d, SRC_TAG, items)
        except Exception as e:
            # 整单失败就退回来一行一行导，能进多少进多少，别整天的数据全丢
            rep.warn("%s 的进仓单整单导入失败（%s），改成逐行导入。" % (d, e))
            iid = None
            for x, it in zip(rows, items):
                try:
                    services.save_inbound(cid, d, SRC_TAG, [it])
                    rep.add("进仓")
                except Exception as e2:
                    rep.skip("进仓 %s %s" % (d, x.get("dye_lot")), str(e2))
            _map_lots(cid, rows, lots)
            continue
        rep.add("进仓", len(items))
        _map_lots(cid, rows, lots)
    return lots


def _map_lots(cid, rows, lots):
    """回查缸号对应的 inbound_item.id。"""
    want = {x["dye_lot"] for x in rows}
    for b in models.list_batches(cid):
        # v_batch_stock 里主键叫 item_id，不是 id
        if b["dye_lot"] in want:
            lots[b["dye_lot"]] = b["item_id"]


def _commit_productions(result, cid, fab, proc, lots, rep, prods=None):
    prods = prods if prods is not None else {}
    for x in result.productions:
        data = {"customer_id": cid,
                "inbound_item_id": lots.get(x.get("dye_lot")),
                "done_date": x.get("done_date") or x.get("ship_date"),
                "process_id": _process_id(x.get("process"), proc),
                "fabric_id": _fabric_id(x.get("fabric"), fab),
                "color": x.get("color") or "",
                "rolls": int(x.get("rolls") or 0),
                "meters": float(x.get("meters") or 0),
                "weight": x.get("weight"), "note": _note(x)}
        try:
            # force=True：老账本是既成事实，坯布对不上也得先进来，警告留给人看
            pid, warns = services.save_production(data, force=True)
            if x.get("key"):
                prods[x["key"]] = pid      # 发货要挂到这条成品上
            rep.add("加工")
            for w in warns:
                rep.warn("加工（%s）：%s" % (_src(x), w))
        except Exception as e:
            rep.skip("加工 %s %s" % (data["done_date"], x.get("fabric")), str(e))
    return prods


def _commit_shipments(result, cid, fab, proc, lots, rep, prods=None):
    """发货按日期归单。老账本一天好几笔，并成一张发货单。"""
    prods = prods or {}
    by_date = {}
    for x in result.shipments:
        by_date.setdefault(x.get("ship_date") or "", []).append(x)

    for d in sorted(by_date):
        if not d:
            for x in by_date[d]:
                rep.skip("发货 %s" % x.get("fabric"), "没有发货日期")
            continue
        items = []
        for x in by_date[d]:
            it = {"fabric_id": _fabric_id(x.get("fabric"), fab),
                  "color": x.get("color") or "",
                  "process_id": _process_id(x.get("process"), proc),
                  "rolls": int(x.get("rolls") or 0),
                  "meters": float(x.get("meters") or 0),
                  "weight": x.get("weight"),
                  "unit_price": float(x.get("unit_price") or 0),
                  "note": _note(x)}
            if x.get("prod_key") in prods:
                # 鹏川：发的是加工好的成品，挂上去成品库存才扣得下来
                it["production_id"] = prods[x["prod_key"]]
            lot, raw = x.get("dye_lot"), x.get("lot_raw")
            if lot and lot in lots:
                it["inbound_item_id"] = lots[lot]
            elif raw or lot:
                # 缸号在入库表里查无此缸（龚松权 4月前结清的老缸），
                # 照样进对账单，只是不挂缸、不扣库存。
                it["note"] = _note(x, "原缸号 %s（入库表里没有这一缸，不扣库存）"
                                      % (raw or lot))
            items.append(it)
        try:
            # force=True：账本上已经发掉的货，超发也得记下来
            _, warns = services.save_shipment(cid, d, "", "", SRC_TAG, items, force=True)
            rep.add("发货", len(items))
            for w in warns:
                rep.warn("发货 %s：%s" % (d, w))
        except Exception as e:
            rep.warn("%s 的发货单整单导入失败（%s），改成逐行导入。" % (d, e))
            for x, it in zip(by_date[d], items):
                try:
                    services.save_shipment(cid, d, "", "", SRC_TAG, [it], force=True)
                    rep.add("发货")
                except Exception as e2:
                    rep.skip("发货 %s %s" % (d, x.get("fabric")), str(e2))


def _commit_payments(result, cid, rep):
    for x in result.payments:
        try:
            models.save_payment(cid, x["pay_date"], float(x["amount"]),
                                x.get("method") or "转账", note=_note(x))
            rep.add("收款")
        except Exception as e:
            rep.skip("收款 %s" % x.get("pay_date"), str(e))
