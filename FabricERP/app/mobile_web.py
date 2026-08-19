# -*- coding: utf-8 -*-
"""手机网页：手机浏览器上查库存、对账、发货记录。只看，不改。

为什么只读：手机上点错了不好收拾，而且录数据要打字，手机上本来就难用。
真要改还是在电脑上改。

样式全部内嵌，不引外部 CSS/JS —— 工厂网络不一定通外网，也免得手机上白屏。
"""

import html

from . import models, services

CSS = """
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;font:15px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
     background:#f2f3f5;color:#1a1a1a;padding-bottom:60px}
a{color:#0b62d0;text-decoration:none}
header{background:#1f6feb;color:#fff;padding:13px 16px;font-size:17px;font-weight:600;
       position:sticky;top:0;z-index:9;display:flex;align-items:center;gap:10px}
header a{color:#fff;opacity:.9;font-weight:400;font-size:15px}
.wrap{padding:12px}
.card{background:#fff;border-radius:10px;padding:14px;margin-bottom:10px;
      box-shadow:0 1px 3px rgba(0,0,0,.07)}
.card h3{margin:0 0 10px;font-size:16px}
.row{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid #f0f0f0}
.row:last-child{border-bottom:0}
.row span:first-child{color:#666}
.num{font-variant-numeric:tabular-nums;font-weight:600}
.red{color:#c0392b}.green{color:#1e8449}.gray{color:#888;font-weight:400}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:#666;font-weight:500;padding:7px 5px;border-bottom:2px solid #eee;
   white-space:nowrap}
td{padding:7px 5px;border-bottom:1px solid #f4f4f4;vertical-align:top}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.tag{display:inline-block;padding:1px 7px;border-radius:9px;font-size:11px;
     background:#eef2f7;color:#4a5568;white-space:nowrap}
.tag.wait{background:#fff4e0;color:#a06000}
.tag.part{background:#e6f0ff;color:#1a5fb4}
.tag.done{background:#e8f5e9;color:#256a2b}
input,button{font:15px inherit;padding:11px;border-radius:8px;border:1px solid #ccc;width:100%}
button{background:#1f6feb;color:#fff;border:0;font-weight:600;margin-top:10px}
.empty{text-align:center;color:#999;padding:34px 10px}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.sub{color:#888;font-size:12px}
"""


def _e(v):
    return html.escape("" if v is None else str(v))


def _n(v, dec=0):
    """数字好读一点：1234.5 → 1,234.5"""
    try:
        f = float(v or 0)
    except (TypeError, ValueError):
        return _e(v)
    return "{:,.{}f}".format(f, dec)


def _shell(title, body, back=None):
    nav = '<a href="%s">‹ 返回</a>' % _e(back) if back else ""
    return ("<!doctype html><html lang=zh-CN><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1,"
            "maximum-scale=1,user-scalable=no'>"
            "<meta name=theme-color content='#1f6feb'>"
            "<title>%s</title><style>%s</style></head><body>"
            "<header>%s<span>%s</span></header><div class=wrap>%s</div>"
            "</body></html>" % (_e(title), CSS, nav, _e(title), body))


def page_login():
    return _shell("面料加工管理", """
      <div class=card>
        <h3>请输入查看口令</h3>
        <p class=sub>口令在电脑上的软件里「设置 → 服务器」能看到。</p>
        <form method=get action=/m>
          <input name=token type=password placeholder="查看口令" autocomplete=off>
          <button type=submit>进入</button>
        </form>
      </div>""")


def page_error(msg):
    return _shell("出错了", "<div class=card><h3>没读出来</h3>"
                            "<p class=sub>%s</p>"
                            "<p><a href=/m>回首页</a></p></div>" % _e(msg))


def page_home():
    """首页：每个客户一张卡，欠多少、压了多少货，一眼看完。"""
    rows = models.list_customers()
    if not rows:
        return _shell("面料加工管理", "<div class=empty>还没有客户</div>")

    total_owe = sum(r["balance"] or 0 for r in rows)
    total_stock = sum(r["stock_meters"] or 0 for r in rows)
    out = ["<div class=card><h3>合计</h3>"
           "<div class=row><span>客户结欠</span>"
           "<span class='num red'>%s 元</span></div>"
           "<div class=row><span>在库坯布</span>"
           "<span class=num>%s 米</span></div></div>" % (_n(total_owe, 2),
                                                         _n(total_stock))]
    for r in rows:
        cid = r["customer_id"]
        bits = ["<div class=row><span>结欠</span><span class='num %s'>%s 元</span></div>"
                % ("red" if (r["balance"] or 0) > 0 else "gray", _n(r["balance"], 2))]
        if r["stock_meters"]:
            bits.append("<div class=row><span>在库坯布</span>"
                        "<span class=num>%s 米（%s 缸）</span></div>"
                        % (_n(r["stock_meters"]), r["open_batches"]))
        if r["fin_meters"]:
            bits.append("<div class=row><span>加工好未发</span>"
                        "<span class=num>%s 米</span></div>" % _n(r["fin_meters"]))
        out.append(
            "<div class=card><h3>%s</h3>%s"
            "<div class=row style='border:0;padding-top:11px'>"
            "<a href='/m/stock?c=%d'>库存 ›</a>"
            "<a href='/m/ships?c=%d'>发货 ›</a>"
            "<a href='/m/statement?c=%d'>对账 ›</a></div></div>"
            % (_e(r["customer"]), "".join(bits), cid, cid, cid))
    return _shell("面料加工管理", "".join(out))


def page_stock(cid):
    c = models.get_customer(cid)
    if not c:
        return page_error("没有这个客户")
    rows = models.list_batches(cid, only_open=True)
    if not rows:
        return _shell("%s·库存" % c["name"],
                      "<div class=empty>没有在库的货</div>", back="/m")

    tag = {"未加工": "wait", "待发货": "part", "部分发货": "part", "已发完": "done"}
    body = ["<div class=card><div class=row><span>共 %d 缸</span>"
            "<span class=num>%s 米</span></div></div>"
            % (len(rows), _n(sum(r["left_meters"] or 0 for r in rows)))]
    body.append("<div class='card scroll'><table>"
                "<tr><th>缸号</th><th>面料</th><th class=n>剩余米</th>"
                "<th>状态</th></tr>")
    for r in rows:
        body.append(
            "<tr><td>%s<div class=sub>%s</div></td>"
            "<td>%s<div class=sub>%s</div></td>"
            "<td class=n>%s<div class=sub>%s卷</div></td>"
            "<td><span class='tag %s'>%s</span></td></tr>"
            % (_e(r["dye_lot"]), _e(r["in_date"]), _e(r["fabric"]), _e(r["color"]),
               _n(r["left_meters"]), r["left_rolls"] or 0,
               tag.get(r["state"], ""), _e(r["state"])))
    body.append("</table></div>")
    return _shell("%s·库存" % c["name"], "".join(body), back="/m")


def page_statement(cid):
    c = models.get_customer(cid)
    if not c:
        return page_error("没有这个客户")
    st = services.statement(cid)

    body = ["<div class=card><h3>%s</h3>"
            "<div class=row><span>期初欠款</span><span class=num>%s</span></div>"
            "<div class=row><span>发货应收</span><span class=num>%s</span></div>"
            "<div class=row><span>已收款</span>"
            "<span class='num green'>%s</span></div>"
            "<div class=row><span>结欠</span>"
            "<span class='num red'>%s 元</span></div>"
            "<div class=row><span>发货合计</span><span class='num gray'>"
            "%s 米 / %s 卷</span></div></div>"
            % (_e(c["name"]), _n(st["opening"], 2), _n(st["billed"], 2),
               _n(st["paid"], 2), _n(st["closing"], 2),
               _n(st["total_meters"]), _n(st["total_rolls"]))]

    # 发货和收款按日期并成一条时间线 —— 手机上就想看「最近发了什么、什么时候打的钱」
    tl = [(r["ship_date"], "发货",
           "%s %s %s" % (r["fabric"], r["color"], r["dye_lot"]),
           "%s米" % _n(r["meters"]), r["amount"], 0) for r in st["items"]]
    tl += [(r["pay_date"], "收款", r["method"] or "", r["ref_no"] or "",
            0, r["amount"]) for r in st["payments"]]
    tl.sort(key=lambda x: (str(x[0] or ""),), reverse=True)
    tl = tl[:80]                      # 手机上只看最近的，一年的账拉不动

    if tl:
        body.append("<div class='card scroll'><h3>最近往来</h3><table>"
                    "<tr><th>日期</th><th>摘要</th><th class=n>金额</th></tr>")
        for d, kind, what, extra, amt, paid in tl:
            body.append(
                "<tr><td>%s<div class=sub>%s</div></td>"
                "<td>%s<div class=sub>%s</div></td><td class=n>%s</td></tr>"
                % (_e(d), _e(kind), _e(what.strip()), _e(extra),
                   ("<span class=green>-%s</span>" % _n(paid, 2)) if paid
                   else _n(amt, 2)))
        body.append("</table></div>")
    else:
        body.append("<div class=empty>还没有往来记录</div>")
    return _shell("%s·对账" % c["name"], "".join(body), back="/m")


def page_ships(cid):
    c = models.get_customer(cid)
    if not c:
        return page_error("没有这个客户")
    rows = list(models.list_shipments(cid))[:40]
    if not rows:
        return _shell("%s·发货" % c["name"],
                      "<div class=empty>还没有发货</div>", back="/m")
    body = ["<div class='card scroll'><table>"
            "<tr><th>日期</th><th>单号</th><th class=n>米数</th>"
            "<th class=n>金额</th></tr>"]
    for r in rows:
        body.append("<tr><td>%s</td><td>%s<div class=sub>%s项</div></td>"
                    "<td class=n>%s<div class=sub>%s卷</div></td>"
                    "<td class=n>%s</td></tr>"
                    % (_e(r["ship_date"]), _e(r["doc_no"]), r["n_items"],
                       _n(r["meters"]), _n(r["rolls"]), _n(r["amount"], 2)))
    body.append("</table></div>")
    return _shell("%s·发货" % c["name"], "".join(body), back="/m")


def render(path, q):
    """路由。q 是 parse_qs 出来的字典。"""
    def cid():
        return int(q.get("c", ["0"])[0] or 0)

    if path in ("/", "/m", "/m/"):
        return page_home()
    if path == "/m/stock":
        return page_stock(cid())
    if path == "/m/statement":
        return page_statement(cid())
    if path == "/m/ships":
        return page_ships(cid())
    return page_error("没有这个页面：" + path)
