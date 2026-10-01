# -*- coding: utf-8 -*-
"""题目渲染组件：把结构化字段或 TeX 组装后用现有渲染管线展示。"""
import streamlit as st

from utils.latex_ops import latex_to_markdown


def assemble_tex(stem_tex: str = "", choices: list | None = None,
                 answer_tex: str = "", solution_tex: str = "") -> str:
    """把结构化字段组装成可渲染的 TeX 文本。"""
    parts = [(stem_tex or "").strip()]
    if choices:
        parts.append("\\begin{choices}")
        parts.extend(f"\\choice{{{{{c}}}}}" for c in choices if str(c).strip())
        parts.append("\\end{choices}")
    tex = "\n".join(p for p in parts if p)
    if (answer_tex or "").strip():
        tex += f"\n\\begin{{answer}}\n{answer_tex.strip()}\n\\end{{answer}}"
    if (solution_tex or "").strip():
        tex += f"\n\\begin{{solutions}}\n{solution_tex.strip()}\n\\end{{solutions}}"
    return tex


def render_question(stem_tex: str = "", choices: list | None = None,
                    answer_tex: str = "", solution_tex: str = "",
                    show_answer: bool = False) -> None:
    """渲染题目。答案/解析默认折叠（show_answer=False 时不渲染答案部分）。"""
    tex = assemble_tex(
        stem_tex, choices,
        answer_tex if show_answer else "",
        solution_tex if show_answer else "",
    )
    md = latex_to_markdown(tex, show_title=False)
    st.markdown(md, unsafe_allow_html=True)


def difficulty_stars(level) -> str:
    try:
        n = int(level or 0)
    except (TypeError, ValueError):
        n = 0
    return "★" * n + "☆" * (5 - n) if n else "未评星"
