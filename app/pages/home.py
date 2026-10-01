# -*- coding: utf-8 -*-
"""首页工作台（M1 版本）：统计概览 + 快捷入口。错题待办在 M2 接入。"""
import streamlit as st

from services import database_service as db
from services.config_service import ai_is_configured, load_config


def render() -> None:
    st.title("🏠 首页")

    stats = db.get_home_stats()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("题库题目", stats["question_count"])
    col2.metric("经典题", stats["classic_count"])
    col3.metric("待审核草稿", stats["draft_pending"])
    col4.metric("待重练错题", stats["mistake_pending"])

    st.divider()

    st.subheader("快捷入口")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("📸 拍题录入", use_container_width=True, type="primary"):
            st.session_state["nav_page"] = "录入中心"
            st.rerun()
    with c2:
        if st.button("📕 扫描错题", use_container_width=True):
            st.session_state["nav_page"] = "录入中心"
            st.session_state["entry_mode"] = "mistake"
            st.rerun()
    with c3:
        if st.button("🖨️ 去打印", use_container_width=True):
            st.session_state["nav_page"] = "组卷打印"
            st.rerun()

    if not ai_is_configured():
        st.info("AI 识别服务尚未配置，拍照识题暂不可用。", icon="🤖")
        if st.button("去配置 AI 服务"):
            st.session_state["nav_page"] = "设置"
            st.rerun()

    if stats["question_count"] == 0 and stats["draft_pending"] == 0:
        st.divider()
        st.markdown("### 🌱 题库还是空的，先拍一道题试试")
        st.write("点击上方「拍题录入」，拍一张教辅书或试卷上的题目照片，"
                 "AI 会自动识别成规范题目，确认后就存入题库了。")

    if stats["draft_pending"]:
        st.divider()
        st.warning(f"有 {stats['draft_pending']} 份 AI 识别草稿等待确认。", icon="📥")
        if st.button("去审核草稿"):
            st.session_state["nav_page"] = "录入中心"
            st.session_state["entry_tab"] = "草稿箱"
            st.rerun()
