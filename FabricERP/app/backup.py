"""启动自动备份，保留最近 N 份。"""

import os
import shutil
import sqlite3
from datetime import datetime

from . import db
from .db import app_dir, get_conn, get_setting

BACKUP_DIR = os.path.join(app_dir(), "backups")


def backup_now(tag=""):
    """用 sqlite 在线备份 API，WAL 模式下也能拿到一致快照。"""
    if not os.path.exists(db.DB_PATH):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"fabric_erp_{stamp}{('_' + tag) if tag else ''}.db"
    dest = os.path.join(BACKUP_DIR, name)

    target = sqlite3.connect(dest)
    try:
        get_conn().backup(target)
    finally:
        target.close()
    _prune()
    return dest


def _prune():
    try:
        keep = int(get_setting("backup_keep", "30"))
    except ValueError:
        keep = 30
    files = sorted(
        (f for f in os.listdir(BACKUP_DIR) if f.startswith("fabric_erp_") and f.endswith(".db")),
        reverse=True)
    for f in files[keep:]:
        try:
            os.remove(os.path.join(BACKUP_DIR, f))
        except OSError:
            pass


def restore(backup_path):
    """从备份恢复：先备份当前库，再覆盖。调用方需在恢复后重启程序。"""
    from .db import close_conn
    backup_now("before_restore")
    close_conn()
    shutil.copy2(backup_path, db.DB_PATH)
    for ext in ("-wal", "-shm"):
        p = db.DB_PATH + ext
        if os.path.exists(p):
            os.remove(p)


def list_backups():
    if not os.path.isdir(BACKUP_DIR):
        return []
    return sorted((os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR)
                   if f.endswith(".db")), reverse=True)
