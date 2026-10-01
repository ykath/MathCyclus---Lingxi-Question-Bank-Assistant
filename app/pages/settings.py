# -*- coding: utf-8 -*-
"""设置页（M1-T02/T03 + M4-T02/T03）：AI 服务配置、知识点树管理、数据备份、高级维护。"""
import os

import streamlit as st

from services.config_service import load_config, save_config, mask_api_key
from services.ocr_service import test_ai_connection
from services import knowledge_service
from services import database_service as db


def _render_ai_settings() -> None:
    st.subheader("🤖 AI 识别服务")
    config = load_config()

    st.caption(f"当前 Key：{mask_api_key(config['ai_api_key'])}")
    with st.form("ai_config_form"):
        base_url = st.text_input("接口地址 (Base URL)", value=config["ai_base_url"])
        model = st.text_input("模型名称", value=config["ai_model_name"],
                              help="需要支持图片理解的视觉模型，如 qwen-vl-plus")
        api_key = st.text_input("API Key（留空表示不修改）", type="password")
        submitted = st.form_submit_button("保存配置", type="primary")
    if submitted:
        updates = {"ai_base_url": base_url, "ai_model_name": model}
        if api_key:
            updates["ai_api_key"] = api_key
        save_config(updates)
        st.success("配置已保存")
        st.rerun()

    if st.button("🔌 测试连接"):
        ok, msg = test_ai_connection()
        (st.success if ok else st.error)(msg)


def _render_child_settings() -> None:
    st.subheader("👶 孩子信息")
    config = load_config()
    from app.pages.wizard import GRADES, TEXTBOOKS
    with st.form("child_form"):
        grade = st.selectbox("年级", GRADES,
                             index=GRADES.index(config["child_grade"]) if config["child_grade"] in GRADES else 3)
        textbook = st.selectbox("教材版本", TEXTBOOKS,
                                index=TEXTBOOKS.index(config["textbook_version"]) if config["textbook_version"] in TEXTBOOKS else 0)
        if st.form_submit_button("保存"):
            save_config({"child_grade": grade, "textbook_version": textbook})
            st.success("已保存")


def _render_knowledge_points() -> None:
    st.subheader("🏷️ 知识点管理")
    points = knowledge_service.get_knowledge_points()
    st.caption(f"共 {len(points)} 个知识点，录入题目时可从中选择。")
    st.write("、".join(points))

    with st.form("add_kp_form", clear_on_submit=True):
        new_point = st.text_input("新增知识点")
        if st.form_submit_button("添加") and new_point.strip():
            knowledge_service.add_knowledge_point(new_point)
            st.success(f"已添加「{new_point.strip()}」")
            st.rerun()

    remove = st.selectbox("删除知识点（不影响已有题目上的标签）", ["（不删除）"] + points)
    if remove != "（不删除）" and st.button(f"删除「{remove}」"):
        knowledge_service.remove_knowledge_point(remove)
        st.rerun()


def _render_advanced() -> None:
    st.subheader("🔧 高级")
    stats = db.get_home_stats()
    st.caption(f"数据库：{db.DB_PATH}（{stats['question_count']} 题）")

    st.markdown("**旧版教师工作台**")
    st.caption("完整功能（语义搜索、统计台、TikZ 维护等）仍在旧版程序中：")
    st.code("streamlit run question_bank_app.py", language="bash")

    st.markdown("**题库迁移**")
    st.caption("把旧 chapters/ 目录下的 .tex 题目导入数据库：")
    st.code("python scripts/migrate_tex_to_db.py", language="bash")

    if st.button("🔄 重新运行首启向导"):
        save_config({"wizard_completed": False})
        st.rerun()


def _render_backup() -> None:
    """M4-T02/T03：一键备份与恢复。"""
    st.subheader("💾 数据备份与恢复")
    from services import backup_service

    if st.button("📦 立即备份", type="primary"):
        with st.spinner("正在打包数据库与图片…"):
            path = backup_service.create_backup(note="手动备份")
        st.success(f"备份完成：{os.path.basename(path)}")
        st.rerun()

    backups = backup_service.list_backups()
    if backups:
        st.caption("历史备份（新→旧）：")
        for b in backups[:5]:
            cols = st.columns([4, 2])
            with cols[0]:
                st.caption(f"{b['name']} · {b['size_mb']} MB · {b.get('created_at', '')}")
            with cols[1]:
                with open(b["path"], "rb") as f:
                    st.download_button("⬇️ 下载", f.read(), file_name=b["name"],
                                       mime="application/zip",
                                       key=f"dl_{b['name']}", use_container_width=True)
    else:
        st.caption("还没有备份。")

    st.markdown("**从备份恢复**（换电脑时使用）")
    uploaded = st.file_uploader("选择备份 zip 文件", type=["zip"], key="restore_uploader")
    if uploaded is not None:
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
            tmp.write(uploaded.getvalue())
            tmp_path = tmp.name
        ok, err = backup_service.validate_backup(tmp_path)
        if not ok:
            st.error(err)
        else:
            st.warning("恢复会覆盖当前题库数据（当前数据会先自动备份一次）。确认无误后再继续。")
            if st.button("⚠️ 确认恢复", type="secondary"):
                ok2, msg = backup_service.restore_backup(tmp_path)
                (st.success if ok2 else st.error)(msg)


def render() -> None:
    st.title("⚙️ 设置")
    _render_ai_settings()
    st.divider()
    _render_child_settings()
    st.divider()
    _render_knowledge_points()
    st.divider()
    _render_backup()
    st.divider()
    _render_advanced()
