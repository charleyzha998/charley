"""面料复合加工厂 ERP —— 程序入口。

双击运行；数据存本目录 data/fabric_erp.db，每次启动和退出自动备份到 backups/。
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    from app import backup, db, server
    from app.db import get_conn
    from app.ui.main_window import MainWindow

    get_conn()              # 建库/建表/建视图（客户端模式则连服务器）

    if db.is_client():
        # 数据在别人电脑上，这台不存东西，也就没什么可备份的
        pass
    else:
        backup.backup_now("start")
        server.autostart()  # 设置里勾了「开机就开服务」就把服务开起来
        # 设置里勾了「开机自动打开本软件」，就把自启动重新指向当前 exe
        # （每次启动都刷新一遍，换新版后仍然指向最新这个文件）
        from app import autostart
        from app.db import get_setting
        if get_setting("autostart_enabled", "0") == "1":
            autostart.set_enabled(True)

    app = MainWindow()

    def on_error(exc, val, tb):
        traceback.print_exception(exc, val, tb)
        from tkinter import messagebox
        messagebox.showerror("程序出错",
                             f"{val}\n\n数据未受影响，请截图反馈。\n\n"
                             f"{''.join(traceback.format_exception(exc, val, tb))[-800:]}")

    app.report_callback_exception = on_error
    app.mainloop()


if __name__ == "__main__":
    main()
