# -*- coding: utf-8 -*-
"""组卷打印（M3）：打印篮 → 打印设置 → 生成 PDF/HTML → 历史与批改登记。"""
import os

import streamlit as st

from services import database_service as db
from services import print_service as ps
from app.components.question_render import difficulty_stars

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ------------------------------------------------------------
# 打印篮（M3-T02）
# ------------------------------------------------------------

def _render_basket() -> None:
    basket = db.basket_list()
    st.subheader(f"🧺 打印篮（{len(basket)} 题）")
    if not basket:
        st.info("打印篮是空的。在「题库」或「错题本」里点「加入打印篮」，题目会出现在这里。")
        return

    for i, item in enumerate(basket, 1):
        with st.container(border=True):
            cols = st.columns([5, 1.5, 1, 1, 1])
            with cols[0]:
                st.markdown(f"**{i}. {item['question_id']}**　"
                            + "　".join(f"`{t}`" for t in item.get("tags", [])))
                st.caption((item.get("stem_tex") or "")[:80] + "…")
            with cols[1]:
                st.caption(difficulty_stars(item.get("difficulty")))
            with cols[2]:
                if st.button("↑", key=f"bk_up_{item['question_id']}",
                             disabled=i == 1, use_container_width=True):
                    db.basket_move(item["question_id"], -1)
                    st.rerun()
            with cols[3]:
                if st.button("↓", key=f"bk_down_{item['question_id']}",
                             disabled=i == len(basket), use_container_width=True):
                    db.basket_move(item["question_id"], 1)
                    st.rerun()
            with cols[4]:
                if st.button("移除", key=f"bk_rm_{item['question_id']}", use_container_width=True):
                    db.basket_remove(item["question_id"])
                    st.rerun()

    if st.button("🗑️ 清空打印篮", use_container_width=True):
        db.basket_clear()
        st.rerun()


# ------------------------------------------------------------
# 打印设置与生成（M3-T03/T04/T05）
# ------------------------------------------------------------

def _render_settings_and_generate() -> None:
    basket = db.basket_list()
    if not basket:
        return

    st.divider()
    st.subheader("⚙️ 打印设置")
    with st.form("print_settings_form"):
        title = st.text_input("练习标题", value="数学练习")
        col1, col2, col3 = st.columns(3)
        with col1:
            paper = st.selectbox("纸张", ["A4", "A5"])
            font_size = st.selectbox("字号", ["偏大", "标准"], index=0,
                                     help="偏大更适合孩子阅读")
        with col2:
            whitespace = st.selectbox("每题作答留白", ["标准", "紧凑", "充裕"], index=1,
                                      help="充裕：解答题留约半页")
            separate = st.checkbox("题目册与答案册分离", value=True,
                                   help="孩子先做题目册，家长用答案册批改")
        with col3:
            with_date = st.checkbox("页眉带日期", value=True)
            with_name_score = st.checkbox("姓名 / 得分栏", value=True)
        submitted = st.form_submit_button("🖨️ 生成打印文件", type="primary",
                                          use_container_width=True)

    if not submitted:
        return

    settings = {
        "paper": paper, "whitespace": whitespace, "separate_answers": separate,
        "font_size": font_size, "title": title,
        "with_date": with_date, "with_name_score": with_name_score,
    }
    basket_id = db.get_or_create_basket()

    # 完整题目数据
    conn_items = db.get_print_job_items(basket_id)
    full_items = []
    for it in conn_items:
        q = db.get_question(it["question_id"])
        full_items.append(q)

    with st.spinner("正在生成打印文件…"):
        # 通道 1：LaTeX PDF
        result = ps.generate_print_pdfs(full_items, settings, basket_id)
        # 通道 2：浏览器 HTML（两种环境都生成，作为降级备份）
        html_content = ps.generate_print_html(full_items, settings)
        html_path = os.path.join(result["dir"], "print.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

    pdf_for_record = result.get("question_pdf") or ""
    db.finalize_print_job(basket_id, title, settings, pdf_for_record)

    if result["errors"]:
        for e in result["errors"]:
            st.error(e)

    st.success("打印文件已生成 ✅")
    dcols = st.columns(3)
    with dcols[0]:
        if result.get("question_pdf"):
            with open(result["question_pdf"], "rb") as f:
                st.download_button("⬇️ 题目册 PDF", f.read(),
                                   file_name=f"{title}-题目册.pdf", mime="application/pdf",
                                   use_container_width=True)
        else:
            st.caption("题目册 PDF：未生成（未安装 LaTeX）")
    with dcols[1]:
        if result.get("answer_pdf"):
            with open(result["answer_pdf"], "rb") as f:
                st.download_button("⬇️ 答案册 PDF", f.read(),
                                   file_name=f"{title}-答案册.pdf", mime="application/pdf",
                                   use_container_width=True)
    with dcols[2]:
        st.download_button("⬇️ 网页打印版（HTML）", html_content,
                           file_name=f"{title}.html", mime="text/html",
                           use_container_width=True,
                           help="双击打开后点右上角打印按钮，无需安装 LaTeX")

    if result["no_xelatex"]:
        st.info("检测到本机未安装 LaTeX，已生成「网页打印版」作为替代。"
                "下载 HTML 后用浏览器打开即可打印。安装 TeX Live 后可获得排版更精美的 PDF。")

    st.caption(f"文件保存在：`{os.path.relpath(result['dir'], BASE_DIR)}`")

    if st.button("📦 已打印完成，收好这份练习", use_container_width=True):
        db.close_basket(basket_id)
        st.success("已收入打印历史，可以到下方「批改登记」记录孩子的做题结果。")
        st.rerun()


# ------------------------------------------------------------
# 打印历史与批改登记（M3-T06/T07）
# ------------------------------------------------------------

def _render_history() -> None:
    jobs = db.list_print_jobs()
    if not jobs:
        return
    st.divider()
    st.subheader("🗂️ 打印历史")
    for job in jobs:
        status_label = {"generated": "已生成", "printed": "已打印", "graded": "已批改"}.get(
            job["status"], job["status"])
        with st.container(border=True):
            cols = st.columns([4, 2, 2, 2])
            with cols[0]:
                st.markdown(f"**{job['title']}**　`{status_label}`")
                st.caption(f"{job['updated_at']} · {job['item_count']} 题 · "
                           f"已批改 {job['graded_count']}/{job['item_count']}")
            with cols[1]:
                pdf_path = job.get("pdf_path") or ""
                if pdf_path and os.path.exists(pdf_path):
                    with open(pdf_path, "rb") as f:
                        st.download_button("🖨️ 重印", f.read(),
                                           file_name=os.path.basename(pdf_path),
                                           mime="application/pdf",
                                           key=f"reprint_{job['print_job_id']}",
                                           use_container_width=True)
                else:
                    st.caption("（HTML 版）")
            with cols[2]:
                if st.button("✏️ 批改登记", key=f"grade_{job['print_job_id']}",
                             use_container_width=True):
                    st.session_state["grading_job_id"] = job["print_job_id"]
                    st.rerun()


def _render_grading(job_id: int) -> None:
    items = db.get_print_job_items(job_id)
    job = next((j for j in db.list_print_jobs(limit=100) if j["print_job_id"] == job_id), None)

    if st.button("← 返回打印页"):
        st.session_state.pop("grading_job_id", None)
        st.rerun()

    st.subheader(f"✏️ 批改登记：{job['title'] if job else f'打印任务 #{job_id}'}")
    st.caption("对照答案册批改后，逐题点选结果。错题会自动更新错题本状态；"
               "普通题做错了可以一键加入错题本。")

    for i, item in enumerate(items, 1):
        qid = item["question_id"]
        with st.container(border=True):
            cols = st.columns([4, 1, 1, 1.5])
            with cols[0]:
                st.markdown(f"**{i}. {qid}**　"
                            + "　".join(f"`{t}`" for t in item.get("tags", [])))
                with st.popover("看答案"):
                    from utils.latex_ops import latex_to_markdown
                    st.markdown(latex_to_markdown(item.get("answer_tex") or "（未录入答案）",
                                                  show_title=False), unsafe_allow_html=True)
            existing = item.get("graded_result")
            with cols[1]:
                label = "✅ 对" + (" ✓" if existing == "correct" else "")
                if st.button(label, key=f"g_ok_{job_id}_{qid}", use_container_width=True,
                             type="primary" if existing == "correct" else "secondary"):
                    _ok, msg = db.record_practice(qid, "correct", print_job_id=job_id)
                    st.toast(msg)
                    st.rerun()
            with cols[2]:
                label = "❌ 错" + (" ✓" if existing == "wrong" else "")
                if st.button(label, key=f"g_no_{job_id}_{qid}", use_container_width=True,
                             type="primary" if existing == "wrong" else "secondary"):
                    _ok, msg = db.record_practice(qid, "wrong", print_job_id=job_id)
                    st.toast(msg)
                    st.rerun()
            with cols[3]:
                if existing == "wrong" and not item.get("in_mistakes"):
                    if st.button("📕 加入错题本", key=f"g_mis_{job_id}_{qid}",
                                 use_container_width=True):
                        _mid, err = db.add_mistake(qid, wrong_reason="其他",
                                                   source_text=job["title"] if job else "")
                        (st.toast if not err else st.warning)(err or "已加入错题本")
                        st.rerun()
                elif item.get("in_mistakes"):
                    st.caption("📕 错题本中")

    if all(i.get("graded_result") for i in items):
        if st.button("🎉 全部批改完成", type="primary", use_container_width=True):
            db.mark_print_job_status(job_id, "graded")
            st.session_state.pop("grading_job_id", None)
            st.rerun()


# ------------------------------------------------------------
# 主渲染
# ------------------------------------------------------------

def render() -> None:
    st.title("🖨️ 组卷打印")

    grading_job = st.session_state.get("grading_job_id")
    if grading_job:
        _render_grading(grading_job)
        return

    _render_basket()
    _render_settings_and_generate()
    _render_history()
