# -*- coding: utf-8 -*-
"""打印服务与打印任务单元测试（M3，离线，不依赖 xelatex）。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import database_service as db
from services import print_service as ps

SAMPLE_ITEMS = [
    {
        "question_id": "Q000001",
        "stem_tex": r"已知函数 $ f(x)=x^2 $，求 $ f(2) $ 的值.",
        "choices": ["$2$", "$4$", "$6$", "$8$"],
        "answer_tex": "B",
        "solution_tex": r"代入得 $ f(2)=4 $.",
        "difficulty": 2,
        "tags": ["函数"],
    },
    {
        "question_id": "Q000002",
        "stem_tex": r"已知数列 $ \{a_n\} $ 满足 $ a_1=1 $，$ a_{n+1}=2a_n $." + "\n\n（1）求通项公式.",
        "choices": [],
        "answer_tex": r"$ a_n=2^{n-1} $",
        "solution_tex": "等比数列.",
        "difficulty": 3,
        "tags": ["数列"],
    },
]

SETTINGS = {
    "paper": "A4", "whitespace": "充裕", "separate_answers": True,
    "font_size": "偏大", "title": "周末练习", "with_date": True, "with_name_score": True,
}


def test_build_tex():
    q_tex, a_tex = ps.build_print_tex(SAMPLE_ITEMS, SETTINGS)
    assert "a4paper" in q_tex and "12pt" in q_tex
    assert "周末练习" in q_tex
    assert "第 1 题" in q_tex and "第 2 题" in q_tex
    assert "\\begin{choices}" in q_tex
    assert "\\choice{{$2$}}" in q_tex
    # 充裕留白：解答题加倍
    assert "\\vspace{14.0cm}" in q_tex
    # 题目册不含答案
    assert "等比数列" not in q_tex
    # 答案册含答案解析且题号对应
    assert "答案与解析" in a_tex
    assert "【答案】" in a_tex and "【解析】" in a_tex
    assert "等比数列" in a_tex


def test_compile_without_xelatex_graceful():
    # 本机无 xelatex 时应返回 NO_XELATEX 且 .tex 已保存
    if ps.xelatex_available():
        return  # 有环境时跳过该断言
    out_dir = tempfile.mkdtemp()
    pdf, err = ps.compile_tex("\\documentclass{ctexart}\\begin{document}hi\\end{document}",
                              out_dir, "t")
    assert pdf is None and err == "NO_XELATEX"
    assert os.path.exists(os.path.join(out_dir, "t.tex"))


def test_generate_html():
    content = ps.generate_print_html(SAMPLE_ITEMS, SETTINGS)
    assert "周末练习" in content
    assert "第 1 题" in content and "第 2 题" in content
    assert "katex" in content.lower()
    assert "page-break" in content          # 题答分离分页
    assert "window.print" in content        # 打印按钮
    assert "A." in content                  # 选项渲染
    assert 'class="blank"' in content       # 留白区
    assert "姓名" in content


def test_print_job_flow():
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    os.remove(path)
    db.ensure_initialized(path)
    try:
        q1 = db.insert_question({"stem_tex": "题1", "tags": ["函数"]}, db_path=path)
        q2 = db.insert_question({"stem_tex": "题2", "tags": ["数列"]}, db_path=path)
        db.basket_add(q1, db_path=path)
        db.basket_add(q2, db_path=path)

        # 排序
        db.basket_move(q2, -1, db_path=path)
        items = db.basket_list(db_path=path)
        assert [i["question_id"] for i in items] == [q2, q1]

        basket_id = db.get_or_create_basket(db_path=path)
        db.finalize_print_job(basket_id, "周末练习", SETTINGS, "/tmp/x.pdf", db_path=path)
        db.close_basket(basket_id, db_path=path)

        jobs = db.list_print_jobs(db_path=path)
        assert len(jobs) == 1 and jobs[0]["status"] == "printed"
        assert jobs[0]["item_count"] == 2

        # 批改登记
        db.record_practice(q2, "correct", print_job_id=basket_id, db_path=path)
        db.record_practice(q1, "wrong", print_job_id=basket_id, db_path=path)
        job_items = db.get_print_job_items(basket_id, db_path=path)
        assert job_items[0]["graded_result"] == "correct"
        assert job_items[1]["graded_result"] == "wrong"

        db.mark_print_job_status(basket_id, "graded", db_path=path)
        assert db.list_print_jobs(db_path=path)[0]["status"] == "graded"

        # 批改后新打印篮是新的 draft
        new_basket = db.get_or_create_basket(db_path=path)
        assert new_basket != basket_id
    finally:
        os.remove(path)


if __name__ == "__main__":
    test_build_tex()
    test_compile_without_xelatex_graceful()
    test_generate_html()
    test_print_job_flow()
    print("M3 print tests PASSED")
