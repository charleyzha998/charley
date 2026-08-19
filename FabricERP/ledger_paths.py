# -*- coding: utf-8 -*-
"""账本目录定位。

坑：这台机器上账本目录的字面名里带冒号（`H:C:...\\Desktop\\客户`），
而且路径字符串经过某些环节会被改写。所以不写死路径，改成扫盘找 ——
认「同时含逸峰/鹏川/龚松权账本的那个文件夹」，一次找到后缓存到 .ledger_dir。
"""
import os

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".ledger_dir")
MARKERS = ("逸峰", "鹏川", "龚松权")


def _looks_right(d):
    try:
        names = os.listdir(d)
    except OSError:
        return False
    hit = {m for m in MARKERS
           if any(m in n and n.lower().endswith((".xls", ".xlsx")) for n in names)}
    return len(hit) >= 3


def _scan():
    import string
    for drv in string.ascii_uppercase:
        root = drv + ":" + os.sep
        if not os.path.isdir(root):
            continue
        for cur, dirs, _files in os.walk(root):
            dirs[:] = [x for x in dirs
                       if not x.startswith("$") and "cachedata" not in x.lower()]
            if os.path.basename(cur) == "客户" and _looks_right(cur):
                return cur
    return None


def ledger_dir(rescan=False):
    if not rescan and os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            d = f.read().strip()
        if d and _looks_right(d):
            return d
    d = _scan()
    if d:
        with open(CACHE, "w", encoding="utf-8") as f:
            f.write(d)
    return d


def path(fname):
    d = ledger_dir()
    return None if d is None else os.path.join(d, fname)


if __name__ == "__main__":
    d = ledger_dir(rescan=True)
    print("账本目录：", repr(d))
    if d:
        for f in sorted(os.listdir(d)):
            print("   ", f)
