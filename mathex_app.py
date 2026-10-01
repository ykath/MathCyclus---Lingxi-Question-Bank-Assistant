# -*- coding: utf-8 -*-
"""
MathEx 家长版 · 主程序入口（M1-T04）

家长专用界面：五页信息架构 + 首启向导。
教师版完整工作台（question_bank_app.py）保持不动，可在「设置 → 高级」中找到入口说明。

运行：
    streamlit run mathex_app.py
"""
import streamlit as st

st.set_page_config(
    page_title="MathEx 题库助手",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

from services.config_service import load_config  # noqa: E402
from services import database_service as db  # noqa: E402
from services.knowledge_service import init_knowledge_points  # noqa: E402

db.ensure_initialized()
init_knowledge_points()

PAGES = ["首页", "录入中心", "题库", "错题本", "组卷打印", "设置"]
PAGE_ICONS = {"首页": "🏠", "录入中心": "📸", "题库": "📚", "错题本": "📕", "组卷打印": "🖨️", "设置": "⚙️"}


def goto(page: str) -> None:
    st.session_state["nav_page"] = page


def main() -> None:
    config = load_config()

    # 首启向导（M1-T01）：未完成时只显示向导
    if not config.get("wizard_completed"):
        from app.pages.wizard import render_wizard
        render_wizard()
        return

    # 侧边栏导航
    with st.sidebar:
        st.markdown("## 📚 MathEx 题库助手")
        if config.get("child_grade"):
            st.caption(f"孩子：{config['child_grade']} · {config.get('textbook_version', '')}")

        if "nav_page" not in st.session_state:
            st.session_state["nav_page"] = "首页"
        page = st.radio(
            "导航", PAGES,
            format_func=lambda p: f"{PAGE_ICONS[p]} {p}",
            key="nav_page",
            label_visibility="collapsed",
        )

        stats = db.get_home_stats()
        st.divider()
        st.caption(f"题库 {stats['question_count']} 题 · 待审核草稿 {stats['draft_pending']} 份")
        if stats["draft_pending"]:
            st.warning(f"📥 有 {stats['draft_pending']} 份识别草稿待确认", icon="📥")

    # 页面路由
    if page == "首页":
        from app.pages.home import render
    elif page == "录入中心":
        from app.pages.entry import render
    elif page == "题库":
        from app.pages.bank import render
    elif page == "错题本":
        from app.pages.mistakes import render
    elif page == "组卷打印":
        from app.pages.printing import render
    else:
        from app.pages.settings import render
    render()


main()
