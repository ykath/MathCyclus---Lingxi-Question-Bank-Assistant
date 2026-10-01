# -*- coding: utf-8 -*-
"""录入中心（M1-T05~T10）：拍题三步走（拍 → 看 → 存）+ 草稿箱。"""
import os

import streamlit as st
from PIL import Image

from services import database_service as db
from services.config_service import ai_is_configured
from services.knowledge_service import get_knowledge_points
from services.ocr_service import ocr_question_images
from app.components.question_render import assemble_tex, render_question

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IMPORTS_DIR = os.path.join(BASE_DIR, "data", "imports")

IMAGE_TYPES = ["png", "jpg", "jpeg", "webp", "bmp"]


# ------------------------------------------------------------
# 第一步「拍」：上传
# ------------------------------------------------------------

def _render_upload() -> None:
    st.subheader("📸 拍题录入")
    st.caption("支持拍照图片、截图，可一次多张；也可以直接把剪贴板里的截图粘贴到上传框。")

    if not ai_is_configured():
        st.warning("AI 识别服务尚未配置。请先到「设置」页填写 API Key。", icon="🤖")
        return

    uploaded = st.file_uploader(
        "上传题目照片（可多选 / 拖拽 / 粘贴）",
        type=IMAGE_TYPES,
        accept_multiple_files=True,
        key="entry_uploader",
    )
    if not uploaded:
        return

    # 缩略图预览
    cols = st.columns(min(len(uploaded), 5))
    for i, file in enumerate(uploaded):
        with cols[i % 5]:
            st.image(file.getvalue(), caption=file.name, use_container_width=True)

    if st.button(f"🤖 开始识别（{len(uploaded)} 张）", type="primary", use_container_width=True):
        _run_ocr(uploaded)


def _run_ocr(uploaded) -> None:
    """逐张识别 → 解析 → 写入草稿箱。"""
    batch_id = db.create_import_batch("ocr", summary=f"拍题录入 {len(uploaded)} 张图片")
    batch_dir = os.path.join(IMPORTS_DIR, f"batch_{batch_id}")
    os.makedirs(batch_dir, exist_ok=True)

    progress = st.progress(0.0, text="准备识别…")
    total_drafts = 0
    errors = []

    for i, file in enumerate(uploaded):
        progress.progress(i / len(uploaded), text=f"正在识别第 {i + 1}/{len(uploaded)} 张：{file.name}")
        try:
            img = Image.open(file)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{file.name}：图片无法打开（{e}）")
            continue

        # 保存原图作为草稿附件（可回溯对照）
        img_path = os.path.join(batch_dir, f"img_{i + 1}.jpg")
        img.convert("RGB").save(img_path, format="JPEG", quality=90)
        rel_img_path = os.path.relpath(img_path, BASE_DIR)

        text, err = ocr_question_images([img])
        if err:
            errors.append(f"{file.name}：{err}")
            db.add_report_item(batch_id, "error", source_file=file.name, reason=err)
            continue

        drafts = db_parse_and_store(text, batch_id, rel_img_path, file.name)
        if drafts == 0:
            errors.append(f"{file.name}：AI 返回的内容中没有识别到题目")
            db.add_report_item(batch_id, "error", source_file=file.name, reason="未解析出题目")
        total_drafts += drafts

    progress.progress(1.0, text="识别完成")
    db.finish_import_batch(batch_id, f"生成草稿 {total_drafts} 份")

    if total_drafts:
        st.success(f"识别完成，共生成 {total_drafts} 份草稿，请在下方「草稿箱」逐题确认。")
    for e in errors:
        st.error(e)
    if errors and not total_drafts:
        st.info("如果照片不清晰，可以重新拍摄后再试；也可以在草稿箱中手工修正。")


def db_parse_and_store(text: str, batch_id: int, img_rel_path: str, file_name: str) -> int:
    from services.ocr_service import parse_ocr_output
    drafts = parse_ocr_output(text)
    for d in drafts:
        draft_id = db.insert_draft(d, batch_id=batch_id)
        db.add_draft_asset(draft_id, img_rel_path, role="source_page_crop",
                           original_file_name=file_name)
        db.add_report_item(batch_id, "needs_review", source_file=file_name)
    return len(drafts)


# ------------------------------------------------------------
# 第二、三步「看 → 存」：草稿箱审核
# ------------------------------------------------------------

def _draft_edit_form(draft: dict) -> None:
    """草稿编辑表单（M1-T05 精简字段模型）。"""
    did = draft["draft_id"]
    knowledge_points = get_knowledge_points()

    stem = st.text_area("题目", value=draft.get("stem_tex") or "", height=120,
                        key=f"draft_stem_{did}")
    choices_text = st.text_area(
        "选项（每行一个，填空/解答题留空）",
        value="\n".join(draft.get("choices") or []), height=100,
        key=f"draft_choices_{did}")
    answer = st.text_area("答案", value=draft.get("answer_tex") or "", height=68,
                          key=f"draft_answer_{did}")
    solution = st.text_area("解析", value=draft.get("solution_tex") or "", height=100,
                            key=f"draft_solution_{did}")

    col1, col2 = st.columns(2)
    with col1:
        difficulty = st.select_slider("难度", options=[1, 2, 3, 4, 5],
                                      value=draft.get("difficulty") or 3,
                                      format_func=lambda n: "★" * n,
                                      key=f"draft_diff_{did}")
    with col2:
        qtype_options = ["单选题", "多选题", "填空题", "解答题"]
        current_type = draft.get("question_type") if draft.get("question_type") in qtype_options else "解答题"
        qtype = st.selectbox("题型", qtype_options, index=qtype_options.index(current_type),
                             key=f"draft_type_{did}")

    existing_tags = [t for t in (draft.get("tags") or []) if t in knowledge_points]
    tags = st.multiselect("知识点标签", knowledge_points, default=existing_tags,
                          key=f"draft_tags_{did}")
    new_tags = st.text_input("新标签（逗号分隔，可留空）", key=f"draft_newtags_{did}",
                             placeholder="如：函数单调性，换元法")
    note = st.text_input("来源 / 备注", value=draft.get("note") or "",
                         key=f"draft_note_{did}", placeholder="如：2025 期末卷 第12题")

    if st.button("💾 保存修改", key=f"draft_save_{did}", use_container_width=True):
        _save_draft_form(did, stem, choices_text, answer, solution,
                         difficulty, qtype, tags, new_tags, note)
        st.success("已保存")
        st.rerun()


def _save_draft_form(did, stem, choices_text, answer, solution,
                     difficulty, qtype, tags, new_tags, note) -> None:
    choices = [c.strip() for c in choices_text.split("\n") if c.strip()]
    extra_tags = [t.strip() for t in new_tags.replace("，", ",").split(",") if t.strip()]
    all_tags = list(dict.fromkeys(list(tags) + extra_tags))
    db.update_draft(did, {
        "stem_tex": stem, "choices": choices, "answer_tex": answer,
        "solution_tex": solution, "difficulty": difficulty,
        "question_type": qtype, "tags": all_tags, "note": note,
    })


def _commit_draft_with_duplicate_check(draft: dict) -> None:
    """M1-T09/T10：入库前重复检测，确认后写正式库。"""
    did = draft["draft_id"]
    confirm_key = f"dup_confirmed_{did}"

    if not st.session_state.get(confirm_key):
        similar = db.find_similar_questions(draft.get("stem_tex") or "")
        if similar:
            top = similar[0]
            st.warning(
                f"题库里可能已有相似题目（{top['question_id']}，相似度 {top['ratio']:.0%}）："
                f"{top['stem_preview']}…"
            )
            col1, col2 = st.columns(2)
            with col1:
                if st.button("仍要入库", key=f"dup_yes_{did}", use_container_width=True):
                    st.session_state[confirm_key] = True
                    st.rerun()
            with col2:
                if st.button("跳过这道题", key=f"dup_no_{did}", use_container_width=True):
                    db.set_draft_status(did, "rejected")
                    st.rerun()
            return

    qid, err = db.commit_draft(did)
    st.session_state.pop(confirm_key, None)
    if err:
        st.error(f"入库失败：{err}")
    else:
        st.success(f"已入库，题目编号 {qid}")
        st.rerun()


def _render_draft_card(draft: dict) -> None:
    did = draft["draft_id"]
    warnings = []
    if draft.get("validation_json"):
        import json
        try:
            warnings = json.loads(draft["validation_json"]).get("warnings", [])
        except (json.JSONDecodeError, AttributeError):
            pass

    status_icon = {"needs_review": "🟡", "ready": "🟢"}.get(draft["review_status"], "⚪")
    label = draft.get("source_label") or f"草稿 #{did}"

    with st.container(border=True):
        st.markdown(f"**{status_icon} {label}**　`{draft.get('question_type') or '未定题型'}`")
        if warnings:
            st.caption("⚠️ " + "；".join(warnings))

        col_img, col_preview = st.columns([1, 1])
        with col_img:
            assets = draft.get("assets") or []
            if assets and os.path.exists(os.path.join(BASE_DIR, assets[0]["file_path"])):
                st.image(os.path.join(BASE_DIR, assets[0]["file_path"]),
                         caption="原始照片", use_container_width=True)
            else:
                st.caption("（无原始图片）")
        with col_preview:
            st.markdown("**排版预览**")
            render_question(draft.get("stem_tex", ""), draft.get("choices"),
                            draft.get("answer_tex", ""), draft.get("solution_tex", ""),
                            show_answer=True)

        with st.expander("✏️ 修改内容", expanded=bool(warnings)):
            _draft_edit_form(draft)

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            if st.button("✅ 通过入库", key=f"draft_commit_{did}",
                         type="primary", use_container_width=True):
                _commit_draft_with_duplicate_check(draft)
        with col_b:
            if draft["review_status"] == "needs_review":
                if st.button("🟢 标记已改好", key=f"draft_ready_{did}", use_container_width=True):
                    db.set_draft_status(did, "ready")
                    st.rerun()
        with col_c:
            if st.button("🗑️ 丢弃", key=f"draft_reject_{did}", use_container_width=True):
                db.set_draft_status(did, "rejected")
                st.rerun()


def _render_draft_box() -> None:
    st.subheader("📥 草稿箱")
    drafts = db.list_drafts(["needs_review", "ready"])
    if not drafts:
        st.success("草稿箱是空的，没有待确认的识别结果 🎉")
        return

    ready_drafts = [d for d in drafts if d["review_status"] == "ready"]
    if ready_drafts:
        if st.button(f"⚡ 全部通过入库（{len(ready_drafts)} 份已改好的草稿）",
                     use_container_width=True):
            ok, fail = 0, 0
            for d in ready_drafts:
                _qid, err = db.commit_draft(d["draft_id"])
                ok, fail = ok + (not err), fail + bool(err)
            st.success(f"批量入库完成：成功 {ok} 份" + (f"，失败 {fail} 份" if fail else ""))
            st.rerun()

    st.caption(f"共 {len(drafts)} 份待确认（🟡 需要检查 / 🟢 已改好）")
    for draft in drafts:
        _render_draft_card(draft)


def render() -> None:
    st.title("📸 录入中心")
    tab_upload, tab_drafts = st.tabs(["拍题录入", "草稿箱"])
    with tab_upload:
        _render_upload()
    with tab_drafts:
        _render_draft_box()
