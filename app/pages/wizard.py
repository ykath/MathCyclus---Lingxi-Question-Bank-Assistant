# -*- coding: utf-8 -*-
"""首次启动向导（M1-T01）：三步完成初始化，完成后不再出现。"""
import streamlit as st

from services.config_service import load_config, save_config
from services.ocr_service import test_ai_connection

GRADES = ["初一", "初二", "初三", "高一", "高二", "高三"]
TEXTBOOKS = ["人教 A 版（2019）", "人教 B 版（2019）", "北师大版", "苏教版", "其他 / 不确定"]


def render_wizard() -> None:
    st.title("👋 欢迎使用 MathEx 题库助手")
    st.caption("首次使用，花 1 分钟完成初始设置。以后可以在「设置」页随时修改。")

    step = st.session_state.get("wizard_step", 1)
    st.progress(step / 3, text=f"第 {step} 步 / 共 3 步")

    config = load_config()

    if step == 1:
        st.subheader("第一步：孩子的年级与教材")
        st.write("用于初始化知识点分类，之后录入题目时会自动推荐。")
        grade = st.selectbox("孩子当前年级", GRADES,
                             index=GRADES.index(config["child_grade"]) if config["child_grade"] in GRADES else 3)
        textbook = st.selectbox("教材版本", TEXTBOOKS,
                                index=TEXTBOOKS.index(config["textbook_version"]) if config["textbook_version"] in TEXTBOOKS else 0)
        if st.button("下一步 →", type="primary", use_container_width=True):
            save_config({"child_grade": grade, "textbook_version": textbook})
            st.session_state["wizard_step"] = 2
            st.rerun()

    elif step == 2:
        st.subheader("第二步：配置 AI 识别服务")
        st.write("拍照识题需要 AI 视觉模型。推荐使用阿里云百炼（qwen-vl-plus），"
                 "也兼容任何 OpenAI 格式的接口。")
        base_url = st.text_input("接口地址 (Base URL)", value=config["ai_base_url"])
        model = st.text_input("模型名称", value=config["ai_model_name"])
        api_key = st.text_input("API Key", value=config["ai_api_key"], type="password",
                                help="在阿里云百炼控制台创建，以 sk- 开头")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔌 测试连接", use_container_width=True):
                save_config({"ai_api_key": api_key, "ai_base_url": base_url, "ai_model_name": model})
                ok, msg = test_ai_connection()
                (st.success if ok else st.error)(msg)
        with col2:
            if st.button("下一步 →", type="primary", use_container_width=True):
                save_config({"ai_api_key": api_key, "ai_base_url": base_url, "ai_model_name": model})
                st.session_state["wizard_step"] = 3
                st.rerun()
        st.caption("暂时没有 Key 也可以先跳过，之后在「设置」页配置；未配置时拍照识别不可用。")

    else:
        st.subheader("第三步：完成 🎉")
        st.write("一切就绪！建议先拍一道题试试：")
        st.markdown("1. 进入 **录入中心**，上传题目照片\n"
                    "2. 确认识别结果，一键入库\n"
                    "3. 在 **题库** 中找到它")
        if st.button("开始使用 →", type="primary", use_container_width=True):
            save_config({"wizard_completed": True})
            st.session_state.pop("wizard_step", None)
            st.rerun()
