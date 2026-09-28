"""Centralized runtime capability diagnostics for document ingestion."""

from __future__ import annotations

import importlib.util
import shutil
from typing import Any

from services.document_parser_service import (
    available_document_parsers,
    preferred_document_parser,
)
from services.mineru_cloud_service import mineru_cloud_config
from services.laya_decision_service import laya_status


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _capability(
    name: str,
    available: bool,
    *,
    detail: str = "",
    required_for: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "available": bool(available),
        "detail": str(detail or ""),
        "required_for": list(required_for or []),
    }


def runtime_capabilities() -> dict[str, Any]:
    """Return one stable, UI/API-friendly snapshot of local parse abilities."""
    cloud = mineru_cloud_config()
    tesseract = shutil.which("tesseract") or ""
    capabilities = [
        _capability(
            "MinerU 云端",
            bool(cloud.get("configured")),
            detail=(cloud.get("base_url") or "未配置 MINERU_API_TOKEN"),
            required_for=["云端版式解析", "扫描 PDF OCR"],
        ),
        _capability("PyMuPDF", _module_available("fitz"), detail="PDF 页面渲染、文本框和内嵌图片", required_for=["PDF 基础解析"]),
        _capability("Pillow", _module_available("PIL"), detail="图片读取、裁剪和 PNG 生成", required_for=["图片裁剪"]),
        _capability("OpenCV", _module_available("cv2"), detail="非文本区域检测、去噪和后续扫描预处理", required_for=["扫描图区域检测"]),
        _capability("Tesseract", bool(tesseract or _module_available("pytesseract")), detail=tesseract or "未找到 tesseract 可执行文件", required_for=["本地题号 OCR（可选）"]),
        _capability(
            "Laya",
            bool(laya_status().get("available")),
            detail=str(laya_status().get("reason") or "optional"),
            required_for=["本地快速分类和候选重排（可选）"],
        ),
    ]
    parser_rows = available_document_parsers()
    selected = preferred_document_parser()
    if selected == "mineru_cloud":
        boundary = "当前自动优先 MinerU 云端；云端失败或未配置时回退到 PyMuPDF。"
    else:
        boundary = "当前自动使用 PyMuPDF 基础解析；配置 MinerU 云端后会优先使用云端版式解析。"
    return {
        "capabilities": capabilities,
        "parsers": parser_rows,
        "preferred_parser": selected,
        "boundary": boundary,
        "opencv_available": next(item["available"] for item in capabilities if item["name"] == "OpenCV"),
        "cloud_configured": bool(cloud.get("configured")),
    }


def capability_warnings(snapshot: dict[str, Any] | None = None) -> list[str]:
    """Return actionable warnings without treating optional components as blockers."""
    report = snapshot or runtime_capabilities()
    warnings: list[str] = []
    by_name = {item["name"]: item for item in report.get("capabilities") or []}
    if not by_name.get("PyMuPDF", {}).get("available"):
        warnings.append("PyMuPDF 不可用，无法进行 PDF 页面级解析。")
    if not by_name.get("Pillow", {}).get("available"):
        warnings.append("Pillow 不可用，图片裁剪和资源生成会失败。")
    if not by_name.get("OpenCV", {}).get("available"):
        warnings.append("OpenCV 未安装，扫描页的非文本图片检测会跳过，但普通文本解析仍可继续。")
    if not report.get("cloud_configured"):
        warnings.append("未配置 MinerU 云端，自动模式会使用 PyMuPDF 回退；扫描 PDF 的版式 OCR 能力会降低。")
    return warnings
