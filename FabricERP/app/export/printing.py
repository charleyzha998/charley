"""打印：生成 A4 HTML → 用系统默认浏览器打开并自动弹出打印对话框。

不引入打印库依赖，工厂电脑上任何浏览器都能打。
送货单打印一式两联（存根联 + 客户联）。
"""

import os
import tempfile
import webbrowser

from .. import models
from ..db import get_setting

CSS = """
@page { size: A4; margin: 12mm 10mm; }
* { box-sizing: border-box; }
body { font-family: "Microsoft YaHei", SimSun, sans-serif; font-size: 12px;
       color: #000; margin: 0; }
.sheet { page-break-after: always; padding-bottom: 6mm; }
.sheet:last-child { page-break-after: auto; }
h1 { text-align: center; font-size: 20px; margin: 0 0 2px; letter-spacing: 3px; }
.sub { text-align: center; font-size: 11px; color: #444; margin-bottom: 8px; }
.copy { text-align: right; font-size: 11px; color: #666; margin-bottom: 2px; }
.meta { width: 100%; margin-bottom: 6px; font-size: 12px; }
.meta td { padding: 2px 4px; }
table.grid { width: 100%; border-collapse: collapse; }
table.grid th, table.grid td { border: 1px solid #555; padding: 4px 5px; }
table.grid th { background: #e8eef7; font-weight: bold; text-align: center; }
td.r { text-align: right; } td.c { text-align: center; } td.l { text-align: left; }
tr.total td { font-weight: bold; background: #f2f5fa; }
.sum { margin-top: 8px; width: 100%; }
.sum td { padding: 3px 6px; font-size: 13px; }
.sum .k { text-align: right; color: #444; }
.sum .v { text-align: right; font-weight: bold; width: 110px;
          border-bottom: 1px solid #999; }
.sign { margin-top: 18px; width: 100%; font-size: 12px; }
.sign td { padding-top: 12px; }
.foot { margin-top: 10px; font-size: 11px; color: #555; text-align: center; }
.note { margin-top: 6px; font-size: 11px; }
@media print { .noprint { display: none; } }
.noprint { text-align: center; padding: 10px; background: #f4f4f4; }
"""

HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{title}</title>
<style>{css}</style></head><body>
<div class="noprint">若未自动弹出打印窗口，请按 Ctrl+P 打印。</div>
{body}
<script>window.onload=function(){{setTimeout(function(){{window.print();}},350);}};</script>
</body></html>"""


def _open(html, name):
    path = os.path.join(tempfile.gettempdir(), name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    webbrowser.open(f"file:///{path.replace(os.sep, '/')}")
    return path


def _company_head():
    name = get_setting("company_name") or ""
    bits = [get_setting("company_address"), get_setting("company_phone")]
    sub = "　".join(b for b in bits if b)
    return name, sub


def _esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _money(x):
    return f"{float(x or 0):,.2f}"


def _meters(x):
    return f"{float(x or 0):,.2f}"


# ---------------- 送货单（一式两联）----------------

def print_delivery(shipment_id):
    head, items = models.get_shipment(shipment_id)
    name, sub = _company_head()

    rows = []
    for it in items:
        rows.append(
            f"<tr><td class='c'>{_esc(it['dye_lot'])}</td>"
            f"<td class='l'>{_esc(it['fabric'])}</td>"
            f"<td class='c'>{_esc(it['color'])}</td>"
            f"<td class='c'>{_esc(it['process'])}</td>"
            f"<td class='r'>{it['rolls']}</td>"
            f"<td class='r'>{_meters(it['meters'])}</td>"
            f"<td class='r'>{it['unit_price']:g}</td>"
            f"<td class='r'>{_money(it['amount'])}</td>"
            f"<td class='l'>{_esc(it['note'])}</td></tr>")
    # 补空行让单据版面稳定
    for _ in range(max(0, 8 - len(items))):
        rows.append("<tr>" + "<td>&nbsp;</td>" * 9 + "</tr>")

    rows.append(
        f"<tr class='total'><td class='c'>合计</td><td colspan='3'></td>"
        f"<td class='r'>{sum(i['rolls'] for i in items)}</td>"
        f"<td class='r'>{_meters(sum(i['meters'] for i in items))}</td><td></td>"
        f"<td class='r'>{_money(sum(i['amount'] for i in items))}</td><td></td></tr>")

    def sheet(copy_name):
        return f"""
<div class="sheet">
  <div class="copy">{copy_name}</div>
  <h1>{_esc(name)} 送货单</h1>
  <div class="sub">{_esc(sub)}</div>
  <table class="meta"><tr>
    <td>客户：<b>{_esc(head['customer'])}</b></td>
    <td>单号：{_esc(head['doc_no'])}</td>
    <td>日期：{_esc(head['ship_date'])}</td>
    <td>车牌：{_esc(head['plate_no'])}</td>
  </tr></table>
  <table class="grid">
    <thead><tr><th>缸号</th><th>面料名称</th><th>颜色</th><th>工艺</th>
      <th>卷数</th><th>米数</th><th>单价</th><th>金额</th><th>备注</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  <div class="note">备注：{_esc(head['note'])}</div>
  <table class="sign"><tr>
    <td>送货人签字：＿＿＿＿＿＿</td>
    <td>收货人签字：＿＿＿＿＿＿</td>
    <td>日期：＿＿＿年＿＿月＿＿日</td>
  </tr></table>
</div>"""

    body = sheet("存根联（工厂留存）") + sheet("客户联（随货交客户）")
    return _open(HTML.format(title=f"送货单 {head['doc_no']}", css=CSS, body=body),
                 f"delivery_{head['doc_no']}.html")


# ---------------- 对账单 ----------------

def print_statement(st):
    cust = st["customer"]
    name, sub = _company_head()
    period = f"{st['date_from'] or '开始'} ~ {st['date_to'] or '至今'}"

    rows = []
    for it in st["items"]:
        rows.append(
            f"<tr><td class='c'>{_esc(it['ship_date'])}</td>"
            f"<td class='c'>{_esc(it['doc_no'])}</td>"
            f"<td class='c'>{_esc(it['dye_lot'])}</td>"
            f"<td class='l'>{_esc(it['fabric'])}</td>"
            f"<td class='c'>{_esc(it['color'])}</td>"
            f"<td class='c'>{_esc(it['process'])}</td>"
            f"<td class='r'>{it['rolls']}</td>"
            f"<td class='r'>{_meters(it['meters'])}</td>"
            f"<td class='r'>{it['unit_price']:g}</td>"
            f"<td class='r'>{_money(it['amount'])}</td></tr>")
    rows.append(
        f"<tr class='total'><td class='c' colspan='3'>合计</td>"
        f"<td class='l'>{len(st['items'])} 行</td><td colspan='2'></td>"
        f"<td class='r'>{st['total_rolls']}</td>"
        f"<td class='r'>{_meters(st['total_meters'])}</td><td></td>"
        f"<td class='r'>{_money(st['billed'])}</td></tr>")

    pay_html = ""
    if st["payments"]:
        prow = "".join(
            f"<tr><td class='c'>{_esc(p['pay_date'])}</td>"
            f"<td class='r'>{_money(p['amount'])}</td>"
            f"<td class='c'>{_esc(p['method'])}</td>"
            f"<td class='l'>{_esc(p['ref_no'])}</td>"
            f"<td class='l'>{_esc(p['note'])}</td></tr>" for p in st["payments"])
        pay_html = f"""
  <div style="margin-top:10px;font-weight:bold;">本期收款</div>
  <table class="grid">
    <thead><tr><th>日期</th><th>金额</th><th>方式</th><th>凭证号</th><th>备注</th></tr></thead>
    <tbody>{prow}
      <tr class='total'><td class='c'>合计</td><td class='r'>{_money(st['paid'])}</td>
      <td colspan='3'></td></tr></tbody>
  </table>"""

    bank = get_setting("company_bank")
    bank_html = f"<div class='note'>收款账号：{_esc(bank)}</div>" if bank else ""

    body = f"""
<div class="sheet">
  <h1>{_esc(name)} 对账单</h1>
  <div class="sub">{_esc(sub)}</div>
  <table class="meta"><tr>
    <td>客户：<b>{_esc(cust['name'])}</b></td>
    <td>对账区间：{_esc(period)}</td>
    <td>制单日期：{_esc(st.get('print_date', ''))}</td>
  </tr></table>
  <table class="grid">
    <thead><tr><th>日期</th><th>送货单号</th><th>缸号</th><th>面料名称</th><th>颜色</th>
      <th>工艺</th><th>卷数</th><th>米数</th><th>单价</th><th>金额</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  {pay_html}
  <table class="sum">
    <tr><td class="k">期初欠款</td><td class="v">{_money(st['opening'])}</td></tr>
    <tr><td class="k">本期应收（加工费）</td><td class="v">{_money(st['billed'])}</td></tr>
    <tr><td class="k">本期已收</td><td class="v">{_money(st['paid'])}</td></tr>
    <tr><td class="k"><b>期末应收（贵司欠款）</b></td>
        <td class="v" style="font-size:15px;">{_money(st['closing'])}</td></tr>
  </table>
  {bank_html}
  <table class="sign"><tr>
    <td>制单：＿＿＿＿</td><td>我方核对：＿＿＿＿</td>
    <td>贵司核对（签章）：＿＿＿＿＿＿</td>
  </tr></table>
  <div class="foot">请核对无误后签章回传。如有异议请于收到后 7 日内提出。</div>
</div>"""

    return _open(HTML.format(title=f"对账单 {cust['name']}", css=CSS, body=body),
                 "statement.html")
