# -*- coding: utf-8 -*-
"""错题本（M2 实现，M1 占位）。"""
import streamlit as st

from services import database_service as db


def render() -> None:
    st.title("📕 错题本")
    stats = db.get_home_stats()
    if stats["question_count"] == 0:
        st.info("先录入一些题目，孩子的错题会在这里按「待重练 / 已掌握」管理。")
    else:
        st.info("错题本功能正在建设中（M2 里程碑）：扫描错题、错因标记、重练状态管理即将上线。")
