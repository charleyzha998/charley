# -*- coding: utf-8 -*-
"""客户端自动更新：连服务器比版本、下载新程序、替换并重启。

只在这台电脑是「客户端」（会计那台）时才有用 —— 服务器那台是版本源头，
自己手动换新 exe 就行。
"""

import hashlib
import json
import os
import subprocess
import sys
import urllib.request

from . import db, version

UPDATE_DIR = "updates"
TMP_NAME = "fabric_erp.new.exe"


def server_target():
    """返回 (base_url, token)。这台没配成客户端就返回 None。"""
    cfg = db._client_config()
    if not cfg:
        return None
    return ("http://%s:%d" % (cfg["host"], int(cfg["port"])),
            cfg.get("token", ""))


def fetch_info(base, timeout=8):
    with urllib.request.urlopen(base + "/ping", timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def check_update():
    """比版本。返回 (是否有新版, 服务器版本名, 服务器 info)。连不上会抛异常。"""
    t = server_target()
    if not t:
        return False, None, None
    base, _token = t
    info = fetch_info(base)
    newer = int(info.get("version_code") or 0) > version.VERSION_CODE
    return newer, info.get("version_name"), info


def download(base, token, info, progress_cb=None, dest=None):
    """下载服务器上的 exe 到 updates/ 目录，校验 sha256。返回文件路径。"""
    updates = os.path.join(db.app_dir(), UPDATE_DIR)
    os.makedirs(updates, exist_ok=True)
    dest = dest or os.path.join(updates, TMP_NAME)

    req = urllib.request.Request(base + "/update/download",
                                 headers={"X-Token": token})
    with urllib.request.urlopen(req, timeout=120) as r:
        total = int(r.headers.get("Content-Length") or 0)
        h = hashlib.sha256()
        done = 0
        with open(dest, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)

    expect = info.get("exe_sha256")
    if expect and h.hexdigest() != expect:
        try:
            os.remove(dest)
        except OSError:
            pass
        raise ValueError("下载的安装包校验不通过（sha256 不一致），请重试。")
    return dest


def install_and_restart(new_path):
    """写一个 update.bat，启动它后本程序要自己退出。

    bat 里不放中文 —— 中文路径通过命令行参数传进去（subprocess 走
    CreateProcessW，Unicode 参数没问题），避免 .bat 文件本身的编码坑。
    它等本程序退出后把新 exe 移到旧 exe 的位置，再重新启动。
    """
    root = db.app_dir()
    current = sys.executable
    bat = os.path.join(root, "update.bat")

    script = (
        "@echo off\r\n"
        "setlocal\r\n"
        "set \"NEW=%~1\"\r\n"
        "set \"OLD=%~2\"\r\n"
        ":wait\r\n"
        "ping 127.0.0.1 -n 2 >nul\r\n"
        "move /y \"%NEW%\" \"%OLD%\" >nul 2>&1\r\n"
        "if exist \"%NEW%\" goto wait\r\n"
        "start \"\" \"%OLD%\"\r\n"
        "endlocal\r\n"
        "del \"%~f0\" >nul 2>&1\r\n"
    )
    with open(bat, "w", encoding="ascii") as f:
        f.write(script)

    subprocess.Popen(
        ["cmd", "/c", bat, new_path, current],
        cwd=root,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
