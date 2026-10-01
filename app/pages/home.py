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

    # 复习建议（M4-T01）：到期该重练的错题
    due = db.suggest_review_mistakes(days=3, limit=8)
    if due:
        st.divider()
        st.subheader(f"📅 今天建议重练（{len(due)} 道）")
        st.caption("规则：待重练且距今 3 天以上没练过的错题，最久未练的排前面。")
        for item in due:
            cols = st.columns([4, 1, 1])
            with cols[0]:
                last = item.get("last_practiced_at") or "从未重练"
                st.caption(f"**{item['question_id']}** · {item.get('wrong_reason') or '未标错因'} · "
                           f"上次：{last[:10]} · " + "、".join(item.get("tags", [])))
            with cols[1]:
                if st.button("去重练", key=f"home_due_{item['question_id']}",
                             use_container_width=True):
                    st.session_state["nav_page"] = "错题本"
                    st.session_state["mistake_detail_qid"] = item["question_id"]
                    st.rerun()
            with cols[2]:
                if st.button("🧺 入篮", key=f"home_due_basket_{item['question_id']}",
                             use_container_width=True):
                    ok, msg = db.basket_add(item["question_id"])
                    (st.toast if ok else st.warning)(msg)
        if st.button("🧺 全部加入打印篮", use_container_width=True):
            added = sum(1 for it in due if db.basket_add(it["question_id"])[0])
            st.toast(f"已加入 {added} 道，其余已在篮中")

    # 备份提醒（M4-T02）：超过 7 天未备份时提示
    from services import backup_service
    days = backup_service.days_since_last_backup()
    if stats["question_count"] > 0 and (days is None or days >= 7):
        st.divider()
        hint = "还没有备份过题库数据" if days is None else f"距离上次备份已经 {days} 天"
        st.info(f"💾 {hint}。建议到「设置 → 数据备份」一键备份，防止数据丢失。")

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
