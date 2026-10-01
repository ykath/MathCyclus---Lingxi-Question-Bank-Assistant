# -*- coding: utf-8 -*-
"""组卷打印（M3 实现完整流程；M2 先提供打印篮查看与管理）。"""
import streamlit as st

from services import database_service as db
from app.components.question_render import difficulty_stars


def render() -> None:
    st.title("🖨️ 组卷打印")

    basket = db.basket_list()
    st.subheader(f"🧺 打印篮（{len(basket)} 题）")
    if not basket:
        st.info("打印篮是空的。在「题库」或「错题本」里点「加入打印篮」，题目会出现在这里。")
    else:
        for i, item in enumerate(basket, 1):
            with st.container(border=True):
                cols = st.columns([5, 2, 1])
                with cols[0]:
                    st.markdown(f"**{i}. {item['question_id']}**　"
                                + "　".join(f"`{t}`" for t in item.get("tags", [])))
                    st.caption((item.get("stem_tex") or "")[:80] + "…")
                with cols[1]:
                    st.caption(difficulty_stars(item.get("difficulty")))
                with cols[2]:
                    if st.button("移除", key=f"basket_rm_{item['question_id']}",
                                 use_container_width=True):
                        db.basket_remove(item["question_id"])
                        st.rerun()
        if st.button("🗑️ 清空打印篮", use_container_width=True):
            db.basket_clear()
            st.rerun()

    st.divider()
    st.info("打印设置与 PDF 导出正在建设中（M3 里程碑）：留白版式、题目册 + 答案册分离、浏览器降级打印即将上线。")
