#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MathEx 家长版 · AI OCR 服务（M1-T07 底层）

- 复用现有 ocr_prompt.txt 排版约束与 ai_service 的 URL 规范化
- 配置来源改为 config_service（界面可配），.env 为兜底
- 输出解析为结构化草稿字段，不写库（入库由 database_service 负责）
"""
import base64
import io
import os
import re

import requests

from services.ai_service import normalize_chat_completions_url, extract_json_obj_from_text
from services.config_service import load_config

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OCR_PROMPT_FILE = os.path.join(BASE_DIR, "ocr_prompt.txt")

DEFAULT_PROMPT = "请识别这张图片中的数学题，并严格按照 LaTeX 格式输出。"


def load_ocr_prompt() -> str:
    if os.path.exists(OCR_PROMPT_FILE):
        with open(OCR_PROMPT_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return DEFAULT_PROMPT


def _pil_to_base64_jpeg(img, max_image_size: int = 1280, quality: int = 80) -> str:
    if max(img.size) > max_image_size:
        ratio = max_image_size / max(img.size)
        img = img.resize((int(img.size[0] * ratio), int(img.size[1] * ratio)))
    buffered = io.BytesIO()
    img.convert("RGB").save(buffered, format="JPEG", quality=quality)
    return base64.b64encode(buffered.getvalue()).decode("utf-8")


def _chat_with_images(prompt: str, images: list, max_tokens: int = 4096,
                      timeout: int = 180) -> tuple[str, str]:
    """发送视觉请求，返回 (内容, 错误信息)。"""
    config = load_config()
    api_key = config.get("ai_api_key", "")
    if not api_key:
        return "", "尚未配置 AI 服务，请到「设置」页填写 API Key"
    if not images:
        return "", "没有提供图片"

    content_parts = [{"type": "text", "text": prompt}]
    for img in images:
        b64 = _pil_to_base64_jpeg(img)
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })

    payload = {
        "model": config.get("ai_model_name") or "qwen-vl-plus",
        "messages": [{"role": "user", "content": content_parts}],
        "max_tokens": max_tokens,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    url = normalize_chat_completions_url(config.get("ai_base_url") or "")

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.exceptions.Timeout:
        return "", f"请求超时（{timeout}s），请检查网络后重试"
    except requests.exceptions.RequestException as e:
        return "", f"网络请求失败：{e}"

    if response.status_code != 200:
        return "", f"识别失败（HTTP {response.status_code}）：{response.text[:300]}"
    try:
        result = response.json()
        return result["choices"][0]["message"]["content"], ""
    except (ValueError, KeyError, IndexError) as e:
        return "", f"AI 返回内容解析失败：{e}"


def ocr_question_images(images: list) -> tuple[str, str]:
    """识别题目图片（可多图），返回 (原始 LaTeX 文本, 错误信息)。"""
    prompt = (
        "你是 OCR 转写助手。你只需要把图片中的内容逐字逐符号转写成 LaTeX 源码。\n"
        "禁止解题、禁止推理、禁止补全缺失步骤、禁止生成答案与解析。\n"
        "如果图片里本身包含答案/解析/提示，请原样转写；否则不要凭空生成。\n\n"
        + load_ocr_prompt()
    )
    return _chat_with_images(prompt, images)


def test_ai_connection() -> tuple[bool, str]:
    """设置页「测试连接」：发送最小文本请求验证配置可用。"""
    config = load_config()
    if not config.get("ai_api_key"):
        return False, "请先填写 API Key"
    url = normalize_chat_completions_url(config.get("ai_base_url") or "")
    payload = {
        "model": config.get("ai_model_name") or "qwen-vl-plus",
        "messages": [{"role": "user", "content": "你好，请回复「连接成功」四个字。"}],
        "max_tokens": 32,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['ai_api_key']}",
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
    except requests.exceptions.RequestException as e:
        return False, f"网络请求失败：{e}"
    if response.status_code == 401:
        return False, "API Key 无效或已过期（HTTP 401），请检查 Key 是否正确"
    if response.status_code == 403:
        return False, "没有访问权限（HTTP 403），请检查 Key 权限或账户余额"
    if response.status_code != 200:
        return False, f"服务返回错误（HTTP {response.status_code}）：{response.text[:200]}"
    return True, "连接成功，AI 服务可用 ✓"


# ------------------------------------------------------------
# OCR 输出解析：---文件名.tex--- 块 → 结构化草稿字段
# ------------------------------------------------------------

_FILENAME_BLOCK = re.compile(r"---(?P<fname>[^\n-][^\n]*?\.tex)---\s*")
_PROBLEM_HEADER = re.compile(
    r"\\begin\{problem\}(?:\[[^\]]*\])?\s*\{(?P<year>.*?)\}\s*\{(?P<ptype>.*?)\}"
    r"\s*\{(?P<paper>.*?)\}\s*\{(?P<num>.*?)\}\s*\{(?P<subject>.*?)\}"
)
_CHOICES_ENV = re.compile(r"\\begin\{choices\}(?:\[.*?\])?(?P<body>.*?)\\end\{choices\}", re.DOTALL)
_ANSWER_ENV = re.compile(r"\\begin\{answer\}(?P<body>.*?)\\end\{answer\}", re.DOTALL)
_SOLUTION_ENV = re.compile(r"\\begin\{solutions?\}(?:\[(?P<opt>.*?)\])?(?P<body>.*?)\\end\{solutions?\}", re.DOTALL)


def _extract_choices(body: str) -> tuple[str, list[str]]:
    """从题干中提取 choices 环境，返回 (去掉选项后的题干, 选项列表)。"""
    match = _CHOICES_ENV.search(body)
    if not match:
        return body.strip(), []
    raw = match.group("body")
    raw = re.sub(r"\\choice", r"\\item", raw)
    parts = [p.strip() for p in re.split(r"\\item", raw) if p.strip()]
    choices = []
    for p in parts:
        if p.startswith("{{") and p.endswith("}}"):
            p = p[2:-2]
        elif p.startswith("{") and p.endswith("}"):
            p = p[1:-1]
        choices.append(p.strip())
    stem = (body[: match.start()] + body[match.end():]).strip()
    return stem, choices


def parse_ocr_output(text: str) -> list[dict]:
    """把 AI OCR 输出解析为草稿字段列表。每个元素可直接传给 insert_draft。"""
    text = (text or "").replace("```latex", "").replace("```tex", "").replace("```", "").strip()
    if not text:
        return []

    # 按 ---文件名.tex--- 切分多题；无文件名标记时整体作为一题
    blocks: list[tuple[str, str]] = []
    matches = list(_FILENAME_BLOCK.finditer(text))
    if matches:
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            blocks.append((m.group("fname"), text[m.end():end]))
    else:
        blocks.append(("", text))

    drafts = []
    for fname, block in blocks:
        header = _PROBLEM_HEADER.search(block)
        meta = {"year": "", "ptype": "", "paper": "", "num": "", "subject": ""}
        if header:
            meta = header.groupdict()
            problem_body_start = header.end()
        else:
            problem_body_start = 0

        problem_end = block.find(r"\end{problem}")
        body = block[problem_body_start:problem_end if problem_end != -1 else len(block)]

        answer = _ANSWER_ENV.search(block)
        solution = _SOLUTION_ENV.search(block)
        answer_tex = answer.group("body").strip() if answer else ""
        solution_tex = solution.group("body").strip() if solution else ""

        stem, choices = _extract_choices(body)
        if not stem.strip() and not choices:
            continue

        # 题型推断（启发式，家长在审核页可改）：
        # 1. 有选项环境 → 单选题
        # 2. 题干含填空下划线 \underline{\hspace...} 或选择题待填括号 (\hspace{...}) → 填空题
        # 3. 题干含（1）（2）小问 → 解答题
        # 4. 只有短答案无解析 → 填空题；其余 → 解答题
        if choices:
            qtype = "单选题"
        elif re.search(r"\\underline\{\\hspace", stem) or re.search(r"\(\\hspace\{[^}]*\}\)", stem):
            qtype = "填空题"
        elif re.search(r"[（(]\s*\d+\s*[)）]", stem):
            qtype = "解答题"
        elif answer_tex and not solution_tex:
            qtype = "填空题"
        else:
            qtype = "解答题"

        tags = [t.strip() for t in re.split(r"[,，]", meta.get("subject", "")) if t.strip()]
        source = " ".join(x for x in [meta.get("year"), meta.get("paper"), f"第{meta['num']}题" if meta.get("num") else ""] if x).strip()

        warnings = []
        if not answer_tex:
            warnings.append("缺少答案")
        if not solution_tex:
            warnings.append("缺少解析")
        if not header:
            warnings.append("未识别到来源信息（年份/试卷/题号）")

        drafts.append({
            "source_item_id": fname,
            "source_label": source or fname or "拍照录入",
            "question_type": qtype,
            "stem_tex": stem,
            "choices": choices,
            "answer_tex": answer_tex,
            "solution_tex": solution_tex,
            "difficulty": 3,
            "tags": tags,
            "note": source,
            "raw_source_text": block.strip(),
            "confidence": {},
            "validation": {"warnings": warnings},
            "review_status": "needs_review",
            "extra": {"meta": meta},
        })
    return drafts
