# -*- coding: utf-8 -*-
"""错题本（M2-T04/T05/T06）：错题列表、状态管理、详情时间线、找同类题。"""
import os
from datetime import date, timedelta

import streamlit as st

from services import database_service as db
from services.knowledge_service import get_knowledge_points
from app.components.question_render import difficulty_stars, render_question

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TABS = {"pending": "📝 待重练", "week": "📅 本周新增", "idle": "⏰ 长期未练", "mastered": "✅ 已掌握"}


# ------------------------------------------------------------
# 卡片与操作
# ------------------------------------------------------------

def _basket_button(qid: str, key_prefix: str) -> None:
    if st.button("🧺 加入打印篮", key=f"{key_prefix}_basket_{qid}", use_container_width=True):
        ok, msg = db.basket_add(qid)
        (st.toast if ok else st.warning)(msg)


def _render_mistake_card(item: dict) -> None:
    qid = item["question_id"]
    with st.container(border=True):
        head = st.columns([4, 2, 2])
        with head[0]:
            st.markdown(f"**{qid}**　`{item.get('wrong_reason') or '未标错因'}`　"
                        + "　".join(f"`{t}`" for t in item.get("tags", [])))
        with head[1]:
            threshold = item.get("pass_threshold") or 2
            st.caption(f"已通过 {item.get('pass_count', 0)}/{threshold} 次 · "
                       f"{difficulty_stars(item.get('difficulty'))}")
        with head[2]:
            st.caption(f"📅 {item.get('wrong_date', '')}")

        render_question(item.get("stem_tex", ""), item.get("choices"), show_answer=False)

        btns = st.columns([1, 1, 1, 1])
        with btns[0]:
            if st.button("查看详情", key=f"m_open_{qid}", use_container_width=True):
                st.session_state["mistake_detail_qid"] = qid
                st.rerun()
        with btns[1]:
            _basket_button(qid, "m")
        with btns[2]:
            if item["status"] == "pending":
                if st.button("✅ 做对了", key=f"m_ok_{qid}", use_container_width=True):
                    _ok, msg = db.record_practice(qid, "correct")
                    st.toast(msg)
                    st.rerun()
        with btns[3]:
            if item["status"] == "pending":
                if st.button("❌ 做错了", key=f"m_no_{qid}", use_container_width=True):
                    _ok, msg = db.record_practice(qid, "wrong")
                    st.toast(msg)
                    st.rerun()
            else:
                if st.button("↩️ 恢复待重练", key=f"m_restore_{qid}", use_container_width=True):
                    db.restore_mistake(qid)
                    st.rerun()


# ------------------------------------------------------------
# 详情页（M2-T05/T06）
# ------------------------------------------------------------

def _render_detail(qid: str) -> None:
    item = db.get_question(qid)
    mistake = db.get_mistake(qid)
    if not item or not mistake:
        st.error("错题记录不存在")
        return

    if st.button("← 返回列表"):
        st.session_state.pop("mistake_detail_qid", None)
        st.rerun()

    st.subheader(f"📕 错题 {qid}")
    status_text = db.MISTAKE_STATUS.get(mistake["status"], mistake["status"])
    st.caption(f"状态：{status_text} · 错因：{mistake.get('wrong_reason') or '未标'} · "
               f"出错日期：{mistake.get('wrong_date')} · 出处：{mistake.get('source_text') or '未填'}")

    col_q, col_photo = st.columns([2, 1])
    with col_q:
        render_question(item["stem_tex"], item.get("choices"),
                        item.get("answer_tex"), item.get("solution_tex"), show_answer=True)
    with col_photo:
        photo_assets = db.list_question_assets(qid, role="source")
        if photo_assets:
            path = os.path.join(BASE_DIR, photo_assets[0]["file_path"])
            if os.path.exists(path):
                st.image(path, caption="孩子原始笔迹", use_column_width=True)

    # 快速批改
    st.markdown("**本次重练结果**")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("✅ 做对了", key=f"d_ok_{qid}", use_container_width=True,
                     disabled=mistake["status"] != "pending"):
            _ok, msg = db.record_practice(qid, "correct")
            st.toast(msg)
            st.rerun()
    with c2:
        if st.button("❌ 做错了", key=f"d_no_{qid}", use_container_width=True,
                     disabled=mistake["status"] != "pending"):
            _ok, msg = db.record_practice(qid, "wrong")
            st.toast(msg)
            st.rerun()
    with c3:
        _basket_button(qid, "d")

    # 错题信息修改
    with st.expander("✏️ 修改错题信息"):
        with st.form(f"mistake_edit_{qid}"):
            reason = st.selectbox("错因", db.WRONG_REASONS,
                                  index=db.WRONG_REASONS.index(mistake["wrong_reason"])
                                  if mistake.get("wrong_reason") in db.WRONG_REASONS else 4)
            wrong_date = st.date_input(
                "出错日期",
                value=date.fromisoformat(mistake["wrong_date"]) if mistake.get("wrong_date") else date.today())
            source_text = st.text_input("出处", value=mistake.get("source_text") or "")
            threshold = st.number_input("做对几次后移出错题本", min_value=1, max_value=5,
                                        value=int(mistake.get("pass_threshold") or 2))
            if st.form_submit_button("保存", type="primary"):
                db.update_mistake(qid, {
                    "wrong_reason": reason,
                    "wrong_date": wrong_date.strftime("%Y-%m-%d"),
                    "source_text": source_text,
                    "pass_threshold": threshold,
                })
                st.success("已保存")
                st.rerun()

    # 练习时间线
    with st.expander("🕘 练习记录", expanded=True):
        records = db.list_practice_records(qid)
        if not records:
            st.caption("还没有练习记录。打印出来让孩子做，做完点「做对了 / 做错了」。")
        for r in records:
            icon = "✅" if r["result"] == "correct" else "❌"
            st.caption(f"{icon} {r['practiced_at']}" + (f" · {r['note']}" if r.get("note") else ""))

    # 找同类题（M2-T06）
    with st.expander("🔁 找同类题（举一反三）", expanded=True):
        similar = db.find_similar_by_tags(qid)
        if not similar:
            st.caption("题库中暂时没有同知识点的其他题目。去录入中心收集一些经典题吧。")
        for s in similar:
            with st.container(border=True):
                st.markdown(f"**{s['question_id']}**　{'🌟' if s.get('is_classic') else ''}　"
                            + "　".join(f"`{t}`" for t in s.get("tags", []))
                            + f"　{difficulty_stars(s.get('difficulty'))}")
                render_question(s.get("stem_tex", ""), show_answer=False)
                _basket_button(s["question_id"], "sim")

    # 危险操作
    with st.expander("⚠️ 更多操作"):
        if mistake["status"] == "mastered":
            if st.button("↩️ 恢复为待重练", key=f"d_restore_{qid}"):
                db.restore_mistake(qid)
                st.rerun()
        if st.button("📤 移出错题本（题目保留在题库）", key=f"d_remove_{qid}"):
            db.remove_mistake(qid)
            st.session_state.pop("mistake_detail_qid", None)
            st.rerun()


# ------------------------------------------------------------
# 主渲染（M2-T04 列表与筛选）
# ------------------------------------------------------------

def render() -> None:
    st.title("📕 错题本")

    detail_qid = st.session_state.get("mistake_detail_qid")
    if detail_qid:
        _render_detail(detail_qid)
        return

    # 错因分布计数条
    counts = db.mistake_reason_counts()
    if counts:
        cols = st.columns(len(db.WRONG_REASONS))
        for i, reason in enumerate(db.WRONG_REASONS):
            cols[i].metric(reason, counts.get(reason, 0))

    tab = st.radio("视图", list(TABS.keys()), format_func=lambda t: TABS[t],
                   horizontal=True, key="mistake_tab", label_visibility="collapsed")

    col1, col2 = st.columns(2)
    with col1:
        reason_filter = st.selectbox("错因筛选", ["全部"] + db.WRONG_REASONS, key="m_reason")
    with col2:
        tag_filter = st.multiselect("知识点筛选", get_knowledge_points(), key="m_tags")

    kwargs = {
        "wrong_reason": None if reason_filter == "全部" else reason_filter,
        "tags": tag_filter or None,
    }
    if tab == "pending":
        items = db.list_mistakes("pending", **kwargs)
    elif tab == "week":
        items = db.list_mistakes("pending", since_date=(date.today() - timedelta(days=7)).isoformat(), **kwargs)
    elif tab == "idle":
        items = db.list_mistakes("pending", idle_days=7, **kwargs)
    else:
        items = db.list_mistakes("mastered", **kwargs)

    if not items:
        if tab == "mastered":
            st.info("还没有已掌握的错题。错题做对足够次数后会自动移到这里。")
        elif db.get_home_stats()["mistake_pending"] == 0 and tab == "pending":
            st.success("孩子没有错题为待重练，真棒 🎉")
            if st.button("📕 去扫描错题"):
                st.session_state["_nav_goto"] = "录入中心"
                st.session_state["entry_mode"] = "mistake"
                st.rerun()
        else:
            st.warning("当前筛选条件下没有错题。")
        return

    st.caption(f"共 {len(items)} 道")
    for item in items:
        _render_mistake_card(item)
