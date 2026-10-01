# -*- coding: utf-8 -*-
"""首页工作台（M2-T07）：统计概览 + 快捷入口 + 待办提醒。"""
import streamlit as st

from services import database_service as db
from services.config_service import ai_is_configured


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

    # 待办：待重练错题速览
    pending_mistakes = db.list_mistakes("pending")
    if pending_mistakes:
        st.divider()
        st.subheader(f"📕 待重练错题（{len(pending_mistakes)}）")
        for item in pending_mistakes[:5]:
            cols = st.columns([4, 1])
            with cols[0]:
                st.caption(f"**{item['question_id']}** · {item.get('wrong_reason') or '未标错因'} · "
                           f"{item.get('wrong_date', '')} · "
                           + "、".join(item.get("tags", [])))
            with cols[1]:
                if st.button("去重练", key=f"home_m_{item['question_id']}",
                             use_container_width=True):
                    st.session_state["nav_page"] = "错题本"
                    st.session_state["mistake_detail_qid"] = item["question_id"]
                    st.rerun()
        if len(pending_mistakes) > 5:
            st.caption(f"… 还有 {len(pending_mistakes) - 5} 道，到「错题本」查看全部")

    # 待办：草稿提醒
    if stats["draft_pending"]:
        st.divider()
        st.warning(f"有 {stats['draft_pending']} 份 AI 识别草稿等待确认。", icon="📥")
        if st.button("去审核草稿"):
            st.session_state["nav_page"] = "录入中心"
            st.rerun()

    # 空状态引导
    if stats["question_count"] == 0 and stats["draft_pending"] == 0:
        st.divider()
        st.markdown("### 🌱 题库还是空的，先拍一道题试试")
        st.write("点击上方「拍题录入」，拍一张教辅书或试卷上的题目照片，"
                 "AI 会自动识别成规范题目，确认后就存入题库了。")
