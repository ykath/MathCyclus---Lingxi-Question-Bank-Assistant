# -*- coding: utf-8 -*-
"""M4 测试：复习建议、备份恢复、PDF 页码解析（离线）。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import database_service as db
from services.pdf_import_service import parse_page_range


def _fresh_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    os.remove(path)
    db.ensure_initialized(path)
    return path


def test_review_suggestion():
    path = _fresh_db()
    try:
        q1 = db.insert_question({"stem_tex": "从未练的错题"}, db_path=path)
        q2 = db.insert_question({"stem_tex": "刚练过的错题"}, db_path=path)
        db.add_mistake(q1, wrong_date="2026-09-20", db_path=path)
        db.add_mistake(q2, wrong_date="2026-09-21", db_path=path)
        # q2 刚刚练习过 → 不应被推荐
        db.record_practice(q2, "wrong", db_path=path)

        due = db.suggest_review_mistakes(days=3, db_path=path)
        ids = [d["question_id"] for d in due]
        assert q1 in ids and q2 not in ids, ids

        # 已掌握的不推荐
        db.record_practice(q1, "correct", db_path=path)
        db.record_practice(q1, "correct", db_path=path)  # 达阈值转已掌握
        # 但刚练过，days=3 也不会推荐；且已掌握直接被排除
        due = db.suggest_review_mistakes(days=3, db_path=path)
        assert all(d["question_id"] != q1 for d in due)
    finally:
        os.remove(path)


def test_backup_restore():
    from services import backup_service
    # 在真实 data/ 上操作：先确保有数据
    db.ensure_initialized()
    qid = db.insert_question({"stem_tex": "备份测试题", "note": "backup-e2e"})

    zip_path = backup_service.create_backup(note="测试备份")
    assert os.path.exists(zip_path)
    ok, err = backup_service.validate_backup(zip_path)
    assert ok, err

    backups = backup_service.list_backups()
    assert any(b["path"] == zip_path for b in backups)
    assert backup_service.days_since_last_backup() == 0

    # 删除题目后恢复
    db.delete_question(qid)
    assert db.get_question(qid) is None
    ok, msg = backup_service.restore_backup(zip_path)
    assert ok, msg
    restored = db.get_question(qid)
    assert restored and restored["note"] == "backup-e2e"

    # 恢复前的自动安全备份也应存在
    assert len(backup_service.list_backups()) >= 2
    # 清理：删掉恢复产生的数据与备份文件，保持环境干净
    db.delete_question(qid)
    for b in backup_service.list_backups():
        os.remove(b["path"])


def test_page_range_parser():
    assert parse_page_range("", 10) == (list(range(1, 11)), "")
    assert parse_page_range("1-3,5", 10)[0] == [1, 2, 3, 5]
    assert parse_page_range("8-10", 10)[0] == [8, 9, 10]
    pages, err = parse_page_range("5-2", 10)
    assert not pages and err
    pages, err = parse_page_range("abc", 10)
    assert not pages and err
    pages, err = parse_page_range("99", 10)
    assert not pages and err


if __name__ == "__main__":
    test_review_suggestion()
    test_backup_restore()
    test_page_range_parser()
    print("M4 tests PASSED")
