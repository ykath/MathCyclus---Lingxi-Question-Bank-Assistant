#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MathEx 家长版 · 数据库初始化脚本（M0-T04）

用法：
    python scripts/init_db.py                 # 初始化默认库 data/mathcyclus.sqlite3
    python scripts/init_db.py --db path.db    # 指定库文件路径
    python scripts/init_db.py --check         # 只校验现有库的表结构是否齐全

特性：
    - 幂等：重复执行不会破坏已有数据（schema 全部为 IF NOT EXISTS）
    - 开启 WAL 与外键约束
    - 执行后输出已创建的表清单
"""
import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PROJECT_ROOT / "db" / "schema.sql"
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"

# schema.sql 中应创建的表（用于 --check 校验）
EXPECTED_TABLES = [
    "question_type",
    "question",
    "question_analysis",
    "question_asset",
    "question_revision",
    "paper",
    "paper_question",
    "book",
    "book_section",
    "book_exercise_question",
    "topic_module",
    "topic",
    "topic_question",
    "import_batch",
    "import_report_item",
    "question_import_draft",
    "question_import_draft_asset",
    "mistake_record",
    "practice_record",
    "print_job",
    "print_job_item",
    "app_setting",
]


def init_db(db_path: Path) -> list[str]:
    """按 schema.sql 初始化数据库，返回实际存在的表清单。"""
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"找不到 schema 文件: {SCHEMA_PATH}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(schema_sql)
        conn.commit()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return sorted(r[0] for r in rows)
    finally:
        conn.close()


def check_db(db_path: Path) -> tuple[list[str], list[str]]:
    """校验库中表是否齐全，返回 (已有表, 缺失表)。"""
    if not db_path.exists():
        return [], list(EXPECTED_TABLES)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        existing = sorted(r[0] for r in rows)
    finally:
        conn.close()
    missing = [t for t in EXPECTED_TABLES if t not in existing]
    return existing, missing


def main() -> int:
    parser = argparse.ArgumentParser(description="MathEx 家长版数据库初始化")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="数据库文件路径")
    parser.add_argument("--check", action="store_true", help="只校验表结构，不建库")
    args = parser.parse_args()

    db_path = Path(args.db)

    if args.check:
        existing, missing = check_db(db_path)
        print(f"[check] 数据库: {db_path}")
        print(f"[check] 已有表 {len(existing)} 张: {', '.join(existing) if existing else '(无)'}")
        if missing:
            print(f"[check] 缺失表 {len(missing)} 张: {', '.join(missing)}")
            return 1
        print("[check] 表结构完整 ✓")
        return 0

    tables = init_db(db_path)
    missing = [t for t in EXPECTED_TABLES if t not in tables]
    print(f"[init] 数据库已就绪: {db_path}")
    print(f"[init] 共 {len(tables)} 张表: {', '.join(tables)}")
    if missing:
        print(f"[init] 警告：以下预期表未创建: {', '.join(missing)}")
        return 1
    print("[init] 所有预期表均已创建 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
