# -*- coding: utf-8 -*-
"""打包成单文件 exe：python build_exe.py

产物：
  dist/面料复合加工管理系统-v<版本号>-<日期-时分>.exe  —— 带版本号+更新日期，归档用
  dist/面料复合加工管理系统.exe                        —— 最新版（固定名，方便双击）

把 exe 拷到工厂电脑任意目录双击即可运行，
数据库和备份会生成在 exe 同级的 data/ 和 backups/ 目录。
注意：dist/data 里是正式账目，打包时不会删它。

发新版：只改 app/version.py 里的 VERSION_NAME，再跑本脚本。
VERSION_CODE 和 BUILD_STAMP（精确到分钟）会自动生成。
"""

import datetime
import importlib
import io
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from app import version  # noqa: E402

NAME = version.APP_NAME


def _stamp_version():
    """把当前时间（精确到分钟）写进 app/version.py。"""
    now = datetime.datetime.now()
    stamp = now.strftime("%Y-%m-%d %H:%M")          # 给人看：2026-08-15 13:30
    code = int(now.strftime("%Y%m%d%H%M"))          # 比较用：202608151330
    file_tag = now.strftime("%Y%m%d-%H%M")          # 文件名用：20260815-1330
    vp = os.path.join(HERE, "app", "version.py")
    s = io.open(vp, encoding="utf-8").read()
    s = re.sub(r"VERSION_CODE = \d+", "VERSION_CODE = %d" % code, s, count=1)
    s = re.sub(r'BUILD_STAMP = "[^"]*"', 'BUILD_STAMP = "%s"' % stamp, s, count=1)
    io.open(vp, "w", encoding="utf-8").write(s)
    importlib.reload(version)
    return file_tag


def main():
    # 只清 build 临时目录；dist 里有 live 数据库(dist/data)和备份，绝不能删
    shutil.rmtree(os.path.join(HERE, "build"), ignore_errors=True)

    file_tag = _stamp_version()
    STAMPED = "%s-v%s-%s" % (NAME, version.VERSION_NAME, file_tag)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",                 # 不弹黑色命令行窗口
        "--name", STAMPED,
        "--hidden-import", "openpyxl",
        # 老账本有 .xls 的（逸峰、鹏川对账、龚松权入库），要靠 xlrd 读
        "--hidden-import", "xlrd",
        # 托盘图标（关闭收到右下角）用 pystray + Pillow
        "--hidden-import", "pystray",
        "--hidden-import", "PIL",
        "--exclude-module", "numpy",
        "--exclude-module", "matplotlib",
        "--noconfirm",
        "main.py",
    ]
    icon = os.path.join(HERE, "icon.ico")
    if os.path.exists(icon):
        cmd += ["--icon", icon]

    print("打包中，首次约需 1-2 分钟…")
    r = subprocess.run(cmd, cwd=HERE)
    if r.returncode != 0:
        print("打包失败")
        return r.returncode

    exe = os.path.join(HERE, "dist", STAMPED + ".exe")
    stable = os.path.join(HERE, "dist", NAME + ".exe")
    # 图标也拷进 dist：窗口标题栏和托盘图标运行时读这个文件，换图标直接换它
    icon_src = os.path.join(HERE, "icon.ico")
    if os.path.exists(icon_src):
        shutil.copy2(icon_src, os.path.join(HERE, "dist", "icon.ico"))
    try:
        shutil.copy2(exe, stable)
        print("\n完成：%s" % exe)
        print("       %s" % stable)
    except OSError as e:
        print("\n完成：%s" % exe)
        print("（固定名 exe 没覆盖成功：%s —— 先关掉正在运行的程序再打包）" % e)
    print("版本：%s" % version.full())
    print("大小：%.1f MB" % (os.path.getsize(exe) / 1024 / 1024))
    print("\n把 exe 拷到工厂电脑任意目录双击即可，数据存在 exe 同级 data/ 目录。")
    print("带版本号+日期的那份留着归档，方便分清是哪一版、什么时候更新的。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
