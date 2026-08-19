# -*- coding: utf-8 -*-
"""系统托盘图标。

点窗口右上角 X 不再退出，而是收进右下角托盘；托盘图标双击恢复、右键退出。
图标取 exe 同级的 icon.ico，想换图标直接换这个文件即可（不用重打包）。
"""

import os
import sys


def _app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def icon_file():
    """exe 同级的 icon.ico，没有就返回 None。"""
    p = os.path.join(_app_dir(), "icon.ico")
    return p if os.path.exists(p) else None


def load_image():
    """托盘图标用的 PIL 图片。优先用 icon.ico，读不到就画一个兜底。"""
    from PIL import Image, ImageDraw
    p = icon_file()
    if p:
        try:
            return Image.open(p)
        except Exception:
            pass
    img = Image.new("RGBA", (64, 64), (31, 111, 235, 255))
    d = ImageDraw.Draw(img)
    d.text((18, 18), "面", fill="white")
    return img
