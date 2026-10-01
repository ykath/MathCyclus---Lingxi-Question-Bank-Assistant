# -*- coding: utf-8 -*-
"""OCR 输出解析器单元测试（离线，不调 AI）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.ocr_service import parse_ocr_output


SAMPLE_SINGLE = r"""---2010-G-浙江卷（理）-22-导数.tex---
\begin{problem}{2010}{G}{浙江卷（理）}{22}{导数}
已知函数 $ f(x)=(x-a)^2(x-b)e^x $，$ a,b\in\mathbb{R} $.

\begin{choices}
\choice{{$1$}}
\choice{{$2$}}
\choice{{$3$}}
\choice{{$4$}}
\end{choices}
\end{problem}
\begin{answer}
A
\end{answer}
\begin{solutions}
由题意得 $ f'(x)=0 $.
\end{solutions}"""

SAMPLE_MULTI = r"""---2024-G-新课标I卷-5-函数.tex---
\begin{problem}{2024}{G}{新课标I卷}{5}{函数}
函数 $ f(x)=x^2 $ 的单调递增区间是 (\hspace{1cm})
\end{problem}
\begin{answer}
$ (0,+\infty) $
\end{answer}
\begin{solutions}
求导即可.
\end{solutions}
---2023-M-杭州模拟-12-数列.tex---
\begin{problem}{2023}{M}{杭州模拟}{12}{数列}
已知数列 $ \{a_n\} $ 满足 $ a_1=1 $，$ a_{n+1}=2a_n $.

（1）求 $ a_n $ 的通项公式.
\end{problem}
\begin{answer}
$ a_n=2^{n-1} $
\end{answer}
\begin{solutions}
由递推式可知为等比数列.
\end{solutions}"""


def test_single_choice():
    drafts = parse_ocr_output(SAMPLE_SINGLE)
    assert len(drafts) == 1, f"应解析出 1 题，实际 {len(drafts)}"
    d = drafts[0]
    assert d["question_type"] == "单选题", d["question_type"]
    assert d["tags"] == ["导数"], d["tags"]
    assert d["choices"] == ["$1$", "$2$", "$3$", "$4$"], d["choices"]
    assert "choices" not in d["stem_tex"], "题干中不应残留选项环境"
    assert d["answer_tex"] == "A"
    assert "f'(x)=0" in d["solution_tex"]
    assert d["source_label"] == "2010 浙江卷（理） 第22题", d["source_label"]


def test_multi_blocks():
    drafts = parse_ocr_output(SAMPLE_MULTI)
    assert len(drafts) == 2, f"应解析出 2 题，实际 {len(drafts)}"
    first, second = drafts
    assert first["question_type"] == "填空题", first["question_type"]
    assert second["question_type"] == "解答题", second["question_type"]
    assert second["tags"] == ["数列"]


def test_empty_and_garbage():
    assert parse_ocr_output("") == []
    assert parse_ocr_output("```latex\n\n```") == []


if __name__ == "__main__":
    test_single_choice()
    test_multi_blocks()
    test_empty_and_garbage()
    print("OCR parser tests PASSED")
