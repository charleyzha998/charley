# -*- coding: utf-8 -*-
"""Windows 开机自启动：把当前 exe 写进注册表 HKCU\\...\\Run。

只在打包成 exe 后才有意义（开发模式没有 exe，注册了也没用）。
每次程序启动时若开关是开的，会重新指向当前 exe —— 这样换了新版 exe
（文件名带版本号）后，开机自启动还是能指到最新这个。
"""

import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "FabricERP"


def _frozen():
    return bool(getattr(sys, "frozen", False))


def set_enabled(enabled):
    """开启/关闭开机自启动。返回是否成功。"""
    if not _frozen():
        return False          # 开发模式没有 exe，不能注册
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                             winreg.KEY_SET_VALUE)
    except OSError:
        return False
    try:
        if enabled:
            # 加引号，防止 exe 路径里有空格
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ,
                              '"%s"' % sys.executable)
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except OSError:
                pass
    finally:
        winreg.CloseKey(key)
    return True


def is_enabled():
    if not _frozen():
        return False
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                             winreg.KEY_READ)
    except OSError:
        return False
    try:
        winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except OSError:
        return False
    finally:
        winreg.CloseKey(key)
