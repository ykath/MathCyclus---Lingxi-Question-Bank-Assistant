# -*- coding: utf-8 -*-
"""
MathEx 家长版 · 备份与恢复服务（M4-T02/T03）

备份内容：SQLite 数据库（一致性快照）+ data/config.json + assets/questions/。
备份文件：backups/mathcyclus_YYYYMMDD_HHmmss.zip（本地私有目录，不入 Git）。
恢复：先校验包完整性，再把当前数据自动备份一次，最后覆盖还原。
"""
import json
import os
import sqlite3
import zipfile
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
ASSETS_DIR = os.path.join(BASE_DIR, "assets", "questions")
BACKUPS_DIR = os.path.join(BASE_DIR, "backups")
DB_PATH = os.path.join(DATA_DIR, "mathcyclus.sqlite3")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

BACKUP_MANIFEST = "backup_manifest.json"


def _snapshot_db(target_path: str) -> None:
    """用 SQLite 备份 API 生成一致性快照（避免 WAL 状态下复制不完整）。"""
    from services.database_service import ensure_initialized
    ensure_initialized()
    src = sqlite3.connect(DB_PATH)
    try:
        dst = sqlite3.connect(target_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def create_backup(note: str = "") -> str:
    """创建备份，返回 zip 路径。"""
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = os.path.join(BACKUPS_DIR, f"mathcyclus_{stamp}.zip")
    # 同一秒内可能连续备份（如恢复前的自动安全备份），文件名去重避免互相覆盖
    seq = 1
    while os.path.exists(zip_path):
        seq += 1
        zip_path = os.path.join(BACKUPS_DIR, f"mathcyclus_{stamp}_{seq}.zip")

    snapshot_path = os.path.join(BACKUPS_DIR, f".snapshot_{stamp}.sqlite3")
    _snapshot_db(snapshot_path)

    manifest = {
        "version": 1,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "app": "MathEx 家长版",
        "note": note,
    }
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(BACKUP_MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
            zf.write(snapshot_path, "data/mathcyclus.sqlite3")
            if os.path.exists(CONFIG_PATH):
                zf.write(CONFIG_PATH, "data/config.json")
            if os.path.isdir(ASSETS_DIR):
                for root, _dirs, files in os.walk(ASSETS_DIR):
                    for name in files:
                        full = os.path.join(root, name)
                        zf.write(full, os.path.relpath(full, BASE_DIR))
    finally:
        if os.path.exists(snapshot_path):
            os.remove(snapshot_path)
    return zip_path


def list_backups() -> list[dict]:
    """备份列表（新→旧）。"""
    if not os.path.isdir(BACKUPS_DIR):
        return []
    items = []
    for name in sorted(os.listdir(BACKUPS_DIR), reverse=True):
        if not (name.startswith("mathcyclus_") and name.endswith(".zip")):
            continue
        full = os.path.join(BACKUPS_DIR, name)
        manifest = {}
        try:
            with zipfile.ZipFile(full) as zf:
                if BACKUP_MANIFEST in zf.namelist():
                    manifest = json.loads(zf.read(BACKUP_MANIFEST).decode("utf-8"))
        except (zipfile.BadZipFile, json.JSONDecodeError):
            pass
        items.append({
            "name": name,
            "path": full,
            "size_mb": round(os.path.getsize(full) / 1024 / 1024, 2),
            "created_at": manifest.get("created_at", ""),
        })
    return items


def validate_backup(zip_path: str) -> tuple[bool, str]:
    """校验备份包：必须是含数据库的合法 zip。"""
    if not os.path.exists(zip_path):
        return False, "备份文件不存在"
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
            if "data/mathcyclus.sqlite3" not in names:
                return False, "备份包中缺少数据库文件（data/mathcyclus.sqlite3）"
            # 试读数据库头部，确认是 SQLite 文件
            header = zf.read("data/mathcyclus.sqlite3")[:16]
            if not header.startswith(b"SQLite format 3"):
                return False, "备份包中的数据库文件已损坏"
    except zipfile.BadZipFile:
        return False, "备份文件不是合法的 zip 包"
    return True, ""


def restore_backup(zip_path: str) -> tuple[bool, str]:
    """恢复备份：先校验 → 自动备份当前数据 → 覆盖还原。"""
    ok, err = validate_backup(zip_path)
    if not ok:
        return False, err

    # 恢复前自动备份当前数据
    if os.path.exists(DB_PATH):
        safety = create_backup(note="恢复前自动备份")
        safety_msg = f"（当前数据已自动备份到 {os.path.basename(safety)}）"
    else:
        safety_msg = ""

    os.makedirs(DATA_DIR, exist_ok=True)
    # 清除旧库的 WAL 日志，避免恢复后被旧日志覆盖
    for suffix in ("-wal", "-shm"):
        sidecar = DB_PATH + suffix
        if os.path.exists(sidecar):
            os.remove(sidecar)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            if member.startswith("data/") or member.startswith("assets/questions/"):
                zf.extract(member, BASE_DIR)
    return True, f"恢复完成{ safety_msg }。请重启应用使数据生效。"


def days_since_last_backup() -> int | None:
    """距上次备份的天数；从未备份返回 None。"""
    backups = list_backups()
    if not backups:
        return None
    latest = backups[0]
    try:
        created = datetime.strptime(latest["created_at"], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        # 从文件名解析 mathcyclus_YYYYMMDD_HHmmss.zip
        try:
            created = datetime.strptime(latest["name"], "mathcyclus_%Y%m%d_%H%M%S.zip")
        except ValueError:
            return None
    return (datetime.now() - created).days
