# -*- coding: utf-8 -*-
"""错题状态机与打印篮单元测试（M2-T03，离线）。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import database_service as db


def _fresh_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    os.remove(path)
    db.ensure_initialized(path)
    return path


def _make_question(db_path, stem="测试题", tags=None) -> str:
    return db.insert_question({"stem_tex": stem, "tags": tags or ["函数"]}, db_path=db_path)


def test_mistake_lifecycle():
    path = _fresh_db()
    try:
        qid = _make_question(path)

        # 加入错题本
        mid, err = db.add_mistake(qid, wrong_reason="计算失误", source_text="期中卷", db_path=path)
        assert mid and not err, err
        # 重复加入被拒绝
        mid2, err2 = db.add_mistake(qid, db_path=path)
        assert mid2 is None and "已经" in err2

        # 第一次做对：仍待重练
        ok, msg = db.record_practice(qid, "correct", db_path=path)
        assert ok, msg
        m = db.get_mistake(qid, db_path=path)
        assert m["status"] == "pending" and m["pass_count"] == 1

        # 做错一次：保持待重练，计数不清零
        db.record_practice(qid, "wrong", db_path=path)
        m = db.get_mistake(qid, db_path=path)
        assert m["status"] == "pending" and m["pass_count"] == 1

        # 第二次做对：达到阈值 2，转已掌握
        ok, msg = db.record_practice(qid, "correct", db_path=path)
        assert "已掌握" in msg, msg
        m = db.get_mistake(qid, db_path=path)
        assert m["status"] == "mastered"

        # 时间线有 3 条记录
        records = db.list_practice_records(qid, db_path=path)
        assert len(records) == 3
        assert records[0]["result"] == "correct"  # 最新在前

        # 恢复待重练
        assert db.restore_mistake(qid, db_path=path)
        m = db.get_mistake(qid, db_path=path)
        assert m["status"] == "pending" and m["pass_count"] == 0

        # 移出错题本
        assert db.remove_mistake(qid, db_path=path)
        assert db.get_mistake(qid, db_path=path) is None
    finally:
        os.remove(path)


def test_mistake_filters():
    path = _fresh_db()
    try:
        q1 = _make_question(path, "题1", ["函数"])
        q2 = _make_question(path, "题2", ["数列"])
        db.add_mistake(q1, wrong_reason="计算失误", wrong_date="2026-09-28", db_path=path)
        db.add_mistake(q2, wrong_reason="概念不清", wrong_date="2026-10-01", db_path=path)

        assert len(db.list_mistakes("pending", db_path=path)) == 2
        assert len(db.list_mistakes("pending", wrong_reason="计算失误", db_path=path)) == 1
        assert len(db.list_mistakes("pending", tags=["数列"], db_path=path)) == 1
        assert len(db.list_mistakes("pending", since_date="2026-10-01", db_path=path)) == 1
        counts = db.mistake_reason_counts(db_path=path)
        assert counts == {"计算失误": 1, "概念不清": 1}, counts
    finally:
        os.remove(path)


def test_similar_by_tags_and_basket():
    path = _fresh_db()
    try:
        mistake_q = _make_question(path, "错题", ["数列", "函数"])
        classic_q = _make_question(path, "经典题", ["数列"])
        other_q = _make_question(path, "无关题", ["几何"])
        db.update_question(classic_q, {"is_classic": True}, db_path=path)
        db.add_mistake(mistake_q, db_path=path)

        similar = db.find_similar_by_tags(mistake_q, db_path=path)
        assert len(similar) == 1 and similar[0]["question_id"] == classic_q, similar

        # 打印篮
        ok, _ = db.basket_add(mistake_q, db_path=path)
        assert ok
        ok, msg = db.basket_add(mistake_q, db_path=path)
        assert not ok and "已在" in msg
        db.basket_add(classic_q, db_path=path)
        items = db.basket_list(db_path=path)
        assert [i["question_id"] for i in items] == [mistake_q, classic_q]
        db.basket_remove(mistake_q, db_path=path)
        assert len(db.basket_list(db_path=path)) == 1
        db.basket_clear(db_path=path)
        assert db.basket_list(db_path=path) == []
    finally:
        os.remove(path)


if __name__ == "__main__":
    test_mistake_lifecycle()
    test_mistake_filters()
    test_similar_by_tags_and_basket()
    print("M2 mistake/basket tests PASSED")
