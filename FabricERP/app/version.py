# -*- coding: utf-8 -*-
"""版本信息。

每次发新版：只改 VERSION_NAME（例如 2.2.0）。
VERSION_CODE 和 BUILD_STAMP 由打包脚本 build_exe.py 自动刷新 ——
BUILD_STAMP 是这一版的最新更新日期，精确到分钟。
"""

APP_NAME = "面料复合加工管理系统"

VERSION_NAME = "2.5.0"                  # 发新版时手动改
VERSION_CODE = 202608181659             # 打包时自动刷新（比较版本用）
BUILD_STAMP = "2026-08-18 16:59"        # 打包时自动刷新（最新更新日期，精确到分钟）


def full():
    """给人看的完整版本，例如 v2.2.0 (2026-08-15 13:30)。"""
    return "v%s (%s)" % (VERSION_NAME, BUILD_STAMP)


def short():
    return "v" + VERSION_NAME
