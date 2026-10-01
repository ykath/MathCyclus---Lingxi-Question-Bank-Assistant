# -*- coding: utf-8 -*-
"""题库（M1-T11/T12/T13）：卡片流浏览、组合筛选、详情轻编辑。"""
import streamlit as st

from services import database_service as db
from services.knowledge_service import get_knowledge_points
from app.components.question_render import (
    assemble_tex, difficulty_stars, render_question,
)

PAGE_SIZES = [10, 20, 50]


# ------------------------------------------------------------
# 搜索与筛选（M1-T12）
# ------------------------------------------------------------

def _render_filters() -> dict:
    with st.container(border=True):
        keyword = st.text_input("🔍 关键词", placeholder="搜索题干、答案、备注、编号…",
                                key="bank_keyword")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            tags = st.multiselect("知识点", get_knowledge_points(), key="bank_tags")
        with col2:
            difficulty = st.multiselect(
                "难度", [1, 2, 3, 4, 5], format_func=lambda n: "★" * n, key="bank_diff")
        with col3:
            types = db.list_question_types()
            type_names = ["全部题型"] + [t["name"] for t in types]
            type_name = st.selectbox("题型", type_names, key="bank_type")
        with col4:
            classic = st.selectbox("经典题", ["全部", "只看经典题"], key="bank_classic")
            printed = st.selectbox("打印状态", ["全部", "已打印过", "未打印过"], key="bank_printed")

    type_id = None
    if type_name != "全部题型":
        type_id = next((t["question_type_id"] for t in types if t["name"] == type_name), None)
    return {
        "keyword": keyword,
        "tags": tags,
        "difficulty": difficulty or None,
        "question_type_id": type_id,
        "is_classic": True if classic == "只看经典题" else None,
        "printed": {"全部": None, "已打印过": True, "未打印过": False}[printed],
    }


# ------------------------------------------------------------
# 题目卡片（M1-T11）
# ------------------------------------------------------------

def _render_card(item: dict) -> None:
    qid = item["question_id"]
    with st.container(border=True):
        header_cols = st.columns([5, 2, 2])
        with header_cols[0]:
            badges = []
            if item.get("is_classic"):
                badges.append("🌟 经典题")
            badges.extend(f"`{t}`" for t in item.get("tags", []))
            st.markdown(f"**{qid}**　" + "　".join(badges))
        with header_cols[1]:
            st.caption(difficulty_stars(item.get("difficulty")))
        with header_cols[2]:
            if item.get("note"):
                st.caption(f"📌 {item['note'][:20]}")

        import json
        try:
            card_choices = json.loads(item["choices_json"]) if item.get("choices_json") else []
        except json.JSONDecodeError:
            card_choices = []
        render_question(item.get("stem_tex", ""), card_choices, show_answer=False)

        btn_cols = st.columns([1, 1, 4])
        with btn_cols[0]:
            if st.button("查看 / 编辑", key=f"bank_open_{qid}", use_container_width=True):
                st.session_state["bank_detail_qid"] = qid
                st.rerun()
        with btn_cols[1]:
            has_answer = bool((item.get("answer_tex") or "").strip())
            if has_answer:
                with st.popover("看答案", use_container_width=True):
                    st.markdown("**【答案】**")
                    from utils.latex_ops import latex_to_markdown
                    st.markdown(latex_to_markdown(item["answer_tex"], show_title=False),
                                unsafe_allow_html=True)
                    if (item.get("solution_tex") or "").strip():
                        st.markdown("**【解析】**")
                        st.markdown(latex_to_markdown(item["solution_tex"], show_title=False),
                                    unsafe_allow_html=True)


# ------------------------------------------------------------
# 详情与轻编辑（M1-T13）
# ------------------------------------------------------------

def _render_detail(qid: str) -> None:
    item = db.get_question(qid)
    if not item:
        st.error("题目不存在")
        return

    if st.button("← 返回列表"):
        st.session_state.pop("bank_detail_qid", None)
        st.rerun()

    st.subheader(f"题目 {qid}")
    if item.get("note"):
        st.caption(f"📌 来源：{item['note']}")

    st.markdown("**当前排版效果**")
    render_question(item["stem_tex"], item.get("choices"),
                    item["answer_tex"], item["solution_tex"], show_answer=True)

    st.divider()
    st.markdown("### ✏️ 修改题目")
    st.caption("直接修改下面的内容即可，保存后自动记录修改历史。懂 LaTeX 的话可以在底部高级模式微调源码。")

    knowledge_points = get_knowledge_points()
    with st.form(f"edit_form_{qid}"):
        stem = st.text_area("题目", value=item["stem_tex"], height=140)
        choices_text = st.text_area("选项（每行一个）",
                                    value="\n".join(item.get("choices") or []), height=100)
        answer = st.text_area("答案", value=item.get("answer_tex") or "", height=68)
        solution = st.text_area("解析", value=item.get("solution_tex") or "", height=120)

        col1, col2, col3 = st.columns(3)
        with col1:
            difficulty = st.select_slider("难度", options=[1, 2, 3, 4, 5],
                                          value=item.get("difficulty") or 3,
                                          format_func=lambda n: "★" * n)
        with col2:
            is_classic = st.checkbox("🌟 标记为经典题", value=bool(item.get("is_classic")))
        with col3:
            types = db.list_question_types()
            type_names = [t["name"] for t in types]
            current = next((t["name"] for t in types
                            if t["question_type_id"] == item.get("question_type_id")), None)
            type_name = st.selectbox("题型", type_names,
                                     index=type_names.index(current) if current in type_names else 0)

        existing_tags = [t for t in item.get("tags", []) if t in knowledge_points]
        extra_existing = [t for t in item.get("tags", []) if t not in knowledge_points]
        tags = st.multiselect("知识点标签", knowledge_points + extra_existing,
                              default=item.get("tags", []))
        new_tags = st.text_input("新标签（逗号分隔，可留空）")
        note = st.text_input("来源 / 备注", value=item.get("note") or "")

        with st.expander("🔬 高级模式：查看完整 LaTeX 源码"):
            st.code(assemble_tex(stem, [c for c in choices_text.split("\n") if c.strip()],
                               answer, solution), language="latex")

        submitted = st.form_submit_button("💾 保存修改", type="primary",
                                          use_container_width=True)

    if submitted:
        choices = [c.strip() for c in choices_text.split("\n") if c.strip()]
        extra_tags = [t.strip() for t in new_tags.replace("，", ",").split(",") if t.strip()]
        all_tags = list(dict.fromkeys(list(tags) + extra_tags))
        type_id = next((t["question_type_id"] for t in db.list_question_types()
                        if t["name"] == type_name), None)
        ok = db.update_question(qid, {
            "stem_tex": stem, "choices": choices, "answer_tex": answer,
            "solution_tex": solution, "difficulty": difficulty,
            "is_classic": is_classic, "tags": all_tags, "note": note,
            "question_type_id": type_id,
        }, note="题库详情页修改")
        if ok:
            st.success("已保存")
            st.rerun()
        else:
            st.error("保存失败")

    with st.expander("⚠️ 危险操作"):
        st.caption("删除后不可恢复（修订记录除外）。")
        if st.button(f"🗑️ 删除题目 {qid}", type="secondary"):
            if db.delete_question(qid):
                st.session_state.pop("bank_detail_qid", None)
                st.success("已删除")
                st.rerun()


# ------------------------------------------------------------
# 主渲染
# ------------------------------------------------------------

def render() -> None:
    st.title("📚 题库")

    detail_qid = st.session_state.get("bank_detail_qid")
    if detail_qid:
        _render_detail(detail_qid)
        return

    filters = _render_filters()

    col1, col2 = st.columns([1, 4])
    with col1:
        page_size = st.selectbox("每页显示", PAGE_SIZES, index=0, key="bank_page_size")

    page = st.session_state.get("bank_page", 1)
    items, total = db.search_questions(page=page, page_size=page_size, **filters)
    total_pages = max(1, (total + page_size - 1) // page_size)
    if page > total_pages:
        page = total_pages
        st.session_state["bank_page"] = page
        items, total = db.search_questions(page=page, page_size=page_size, **filters)

    with col2:
        st.caption(f"共 {total} 题 · 第 {page}/{total_pages} 页")

    if not items:
        if total == 0 and not any([filters["keyword"], filters["tags"], filters["difficulty"],
                                   filters["question_type_id"], filters["is_classic"]]):
            st.info("题库还是空的。去「录入中心」拍一道题试试 📸")
        else:
            st.warning("没有符合条件的题目，试试放宽筛选条件。")
        return

    for item in items:
        _render_card(item)

    # 分页
    nav_cols = st.columns([1, 2, 1])
    with nav_cols[0]:
        if page > 1 and st.button("← 上一页", use_container_width=True):
            st.session_state["bank_page"] = page - 1
            st.rerun()
    with nav_cols[2]:
        if page < total_pages and st.button("下一页 →", use_container_width=True):
            st.session_state["bank_page"] = page + 1
            st.rerun()
