# -*- coding: utf-8 -*-
"""
MathEx 家长版 · PDF 导入服务（M4-T04 最小闭环）

路线（与 docs/planning/pdf_import_pipeline.md 一致，范围收敛为 MVP）：
    PDF → PyMuPDF 逐页渲染为图片 → 每页 OCR → 按 ---文件名.tex--- 切题 → 草稿箱
MinerU 等深度版面解析为可选增强，本服务不依赖。
"""
import os

import fitz  # PyMuPDF
from PIL import Image
import io

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMPORTS_DIR = os.path.join(BASE_DIR, "data", "imports")


def get_pdf_page_count(pdf_bytes: bytes) -> tuple[int, str]:
    """读取 PDF 页数，返回 (页数, 错误信息)。"""
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            if doc.needs_pass:
                return 0, "PDF 已加密，暂不支持受密码保护的文件"
            return doc.page_count, ""
    except Exception as e:  # noqa: BLE001
        return 0, f"PDF 无法打开：{e}"


def render_pdf_pages(pdf_bytes: bytes, page_numbers: list[int],
                     dpi: int = 160) -> tuple[list[tuple[int, Image.Image]], str]:
    """把指定页（1 起）渲染为 PIL 图片，返回 ([(页码, 图片)], 错误信息)。"""
    images = []
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            if doc.needs_pass:
                return [], "PDF 已加密，暂不支持受密码保护的文件"
            for num in page_numbers:
                if not 1 <= num <= doc.page_count:
                    return [], f"页码 {num} 超出范围（共 {doc.page_count} 页）"
                pix = doc.load_page(num - 1).get_pixmap(dpi=dpi, alpha=False)
                with Image.open(io.BytesIO(pix.tobytes("png"))) as img:
                    img.load()
                    images.append((num, img.convert("RGB").copy()))
        return images, ""
    except Exception as e:  # noqa: BLE001
        return [], f"PDF 页面渲染失败：{e}"


def save_page_image(img: Image.Image, batch_id: int, page_num: int) -> str:
    """保存页面图片到导入批次目录，返回相对路径。"""
    batch_dir = os.path.join(IMPORTS_DIR, f"batch_{batch_id}")
    os.makedirs(batch_dir, exist_ok=True)
    path = os.path.join(batch_dir, f"page_{page_num:03d}.jpg")
    img.save(path, format="JPEG", quality=90)
    return os.path.relpath(path, BASE_DIR)


def parse_page_range(text: str, page_count: int) -> tuple[list[int], str]:
    """解析页码输入：支持 '1-5,8,10-12'；空串表示全部。"""
    text = (text or "").strip()
    if not text:
        return list(range(1, page_count + 1)), ""
    pages: set[int] = set()
    for part in text.replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part or "–" in part:
            seg = re_split_dash(part)
            if not seg:
                return [], f"页码范围「{part}」格式不正确"
            start, end = seg
            if start > end:
                return [], f"页码范围「{part}」起点大于终点"
            pages.update(range(start, end + 1))
        else:
            if not part.isdigit():
                return [], f"页码「{part}」不是数字"
            pages.add(int(part))
    result = sorted(p for p in pages if 1 <= p <= page_count)
    if not result:
        return [], "所选页码都超出了 PDF 页数范围"
    return result, ""


def re_split_dash(part: str) -> tuple[int, int] | None:
    for dash in ("-", "–"):
        if dash in part:
            a, b = part.split(dash, 1)
            if a.strip().isdigit() and b.strip().isdigit():
                return int(a), int(b)
    return None
