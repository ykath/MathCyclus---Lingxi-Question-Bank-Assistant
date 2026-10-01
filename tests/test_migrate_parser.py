# -*- coding: utf-8 -*-
"""题库迁移解析器单元测试（离线）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.migrate_tex_to_db import parse_question_tex, build_canonical_tex


SAMPLE_QUESTION = r"""% === Begin Label Data ===
% ID: 1024
% 难度星级: 4
% 标签: 数列，函数
% 备注: 经典压轴题
% === End  Label Data ===

\begin{problem}{2010}{G}{浙江卷（理）}{22}{数列}
已知数列 $ \{a_n\} $ 满足 $ a_1=1 $，$ a_{n+1}=2a_n $.

\begin{choices}
\choice{{$ a_n=2^{n-1} $}}
\choice{{$ a_n=2^n $}}
\end{choices}
\end{problem}
\begin{answer}
A
\end{answer}
\begin{solutions}
由递推式可知公比为 $ 2 $.
\end{solutions}
\begin{solutions}[另解]
数学归纳法.
\end{solutions}"""


def test_parse_full_question():
    p = parse_question_tex(SAMPLE_QUESTION)
    assert p["tags"] == ["数列", "函数"]
    assert p["difficulty"] == 4
    assert p["note"] == "经典压轴题"
    assert p["question_type_name"] == "单选题"
    assert p["choices"] == ["$ a_n=2^{n-1} $", "$ a_n=2^n $"]
    assert p["answer_tex"] == "A"
    assert "由递推式可知" in p["solution_tex"]
    assert "【另解】" in p["solution_tex"], "多解析应保留另解标注"
    assert p["source"] == "2010 浙江卷（理） 第22题"
    assert "choices" not in p["stem_tex"]


def test_canonical_tex_roundtrip():
    p = parse_question_tex(SAMPLE_QUESTION)
    canonical = build_canonical_tex(p)
    assert "\\begin{choices}" in canonical
    assert "\\begin{answer}" in canonical
    assert "\\begin{solutions}" in canonical
    assert "$ a_n=2^{n-1} $" in canonical


def test_missing_problem_env_raises():
    try:
        parse_question_tex("\\section{2005}\n\\input{chapters/数列/2005/xxx}")
    except ValueError:
        return
    raise AssertionError("缺少 problem 环境时应抛出 ValueError")


if __name__ == "__main__":
    test_parse_full_question()
    test_canonical_tex_roundtrip()
    test_missing_problem_env_raises()
    print("migration parser tests PASSED")
