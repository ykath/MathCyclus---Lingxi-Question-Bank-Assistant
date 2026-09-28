"""Detect and crop non-text visual regions from rendered document pages."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from PIL import Image


def normalize_region_bbox(value: Any, width: int, height: int) -> list[int]:
    """Clamp a user-edited image rectangle to valid pixel coordinates."""
    try:
        raw = [int(round(float(item))) for item in value[:4]]
    except (TypeError, ValueError, IndexError):
        return []
    if len(raw) < 4:
        return []
    x0, y0, x1, y1 = raw
    x0, x1 = sorted((max(0, min(width, x0)), max(0, min(width, x1))))
    y0, y1 = sorted((max(0, min(height, y0)), max(0, min(height, y1))))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return []
    return [x0, y0, x1, y1]


def opencv_available() -> bool:
    return importlib.util.find_spec("cv2") is not None


def _merge_boxes(boxes: list[list[int]], gap: int = 18) -> list[list[int]]:
    pending = [list(box) for box in boxes]
    merged: list[list[int]] = []
    while pending:
        current = pending.pop(0)
        changed = True
        while changed:
            changed = False
            remaining = []
            for candidate in pending:
                separated = (
                    candidate[2] + gap < current[0]
                    or current[2] + gap < candidate[0]
                    or candidate[3] + gap < current[1]
                    or current[3] + gap < candidate[1]
                )
                if separated:
                    remaining.append(candidate)
                    continue
                current = [
                    min(current[0], candidate[0]),
                    min(current[1], candidate[1]),
                    max(current[2], candidate[2]),
                    max(current[3], candidate[3]),
                ]
                changed = True
            pending = remaining
        merged.append(current)
    return sorted(merged, key=lambda box: (box[1], box[0]))


def _odd(value: int, minimum: int = 3) -> int:
    value = max(minimum, int(value))
    return value if value % 2 else value + 1


def _preprocess_scan(
    image: Any,
    cv2: Any,
    *,
    denoise: bool = True,
    threshold_block_size: int = 35,
    threshold_c: int = 15,
) -> Any:
    """Build a dimension-preserving mask for scanned pages.

    Keeping the original dimensions is important because text and image boxes
    from PyMuPDF are in the original page coordinate system.
    """
    grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if denoise:
        grayscale = cv2.medianBlur(grayscale, 3)
    block_size = _odd(threshold_block_size, 3)
    return cv2.adaptiveThreshold(
        grayscale,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        block_size,
        int(threshold_c),
    )


def _box_overlap_ratio(first: list[int], second: list[float]) -> float:
    if len(first) < 4 or len(second) < 4:
        return 0.0
    x0 = max(float(first[0]), float(second[0]))
    y0 = max(float(first[1]), float(second[1]))
    x1 = min(float(first[2]), float(second[2]))
    y1 = min(float(first[3]), float(second[3]))
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    area = max(1.0, (first[2] - first[0]) * (first[3] - first[1]))
    return intersection / area


def _candidate_quality(
    box: list[int],
    *,
    width: int,
    height: int,
    text_boxes: list[list[float]],
    ink_ratio: float,
    border_margin: int,
) -> tuple[float, float]:
    """Return (score, text_overlap) for a detected visual candidate."""
    x0, y0, x1, y1 = box
    region_width = max(1, x1 - x0)
    region_height = max(1, y1 - y0)
    area_ratio = (region_width * region_height) / max(1.0, float(width * height))
    text_overlap = max((_box_overlap_ratio(box, candidate) for candidate in text_boxes), default=0.0)
    touches_edge = int(
        x0 <= border_margin
        or y0 <= border_margin
        or x1 >= width - border_margin
        or y1 >= height - border_margin
    )
    aspect = region_width / max(1.0, float(region_height))
    aspect_score = 1.0 if 0.12 <= aspect <= 8.0 else 0.55
    area_score = min(1.0, max(0.0, area_ratio / 0.02))
    ink_score = min(1.0, max(0.0, ink_ratio / 0.08))
    score = (
        0.42 * area_score
        + 0.28 * ink_score
        + 0.20 * aspect_score
        - 0.34 * text_overlap
        - 0.12 * touches_edge
    )
    return max(0.0, min(1.0, score)), text_overlap


def detect_visual_regions(
    image_path: str | Path,
    *,
    text_boxes: list[list[float]] | None = None,
    min_area_ratio: float = 0.0015,
    max_area_ratio: float = 0.65,
    min_width: int = 32,
    min_height: int = 24,
    merge_gap: int = 18,
    morphology_kernel_size: int = 7,
    morphology_iterations: int = 2,
    text_padding: int = 3,
    border_margin: int = 8,
    denoise: bool = True,
    threshold_block_size: int = 35,
    threshold_c: int = 15,
    minimum_quality: float = 0.12,
) -> list[dict[str, Any]]:
    if not opencv_available():
        return []
    import cv2

    source = Path(image_path)
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法读取页面图片：{source}")
    height, width = image.shape[:2]
    normalized_text_boxes = [list(box[:4]) for box in (text_boxes or []) if len(box) >= 4]
    binary = _preprocess_scan(
        image,
        cv2,
        denoise=denoise,
        threshold_block_size=threshold_block_size,
        threshold_c=threshold_c,
    )
    for raw_box in normalized_text_boxes:
        if len(raw_box) < 4:
            continue
        x0, y0, x1, y1 = [int(round(value)) for value in raw_box[:4]]
        cv2.rectangle(
            binary,
            (max(0, x0 - int(text_padding)), max(0, y0 - int(text_padding))),
            (min(width, x1 + int(text_padding)), min(height, y1 + int(text_padding))),
            0,
            -1,
        )
    kernel_size = _odd(morphology_kernel_size, 3)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    connected = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=max(1, int(morphology_iterations)))
    contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    page_area = float(width * height)
    boxes = []
    for contour in contours:
        x, y, region_width, region_height = cv2.boundingRect(contour)
        area_ratio = (region_width * region_height) / page_area
        if area_ratio < min_area_ratio or area_ratio > max_area_ratio:
            continue
        if region_width < int(min_width) or region_height < int(min_height):
            continue
        box = [x, y, x + region_width, y + region_height]
        crop_mask = connected[y : y + region_height, x : x + region_width]
        ink_ratio = float(cv2.countNonZero(crop_mask)) / max(1.0, float(region_width * region_height))
        quality, text_overlap = _candidate_quality(
            box,
            width=width,
            height=height,
            text_boxes=normalized_text_boxes,
            ink_ratio=ink_ratio,
            border_margin=int(border_margin),
        )
        if text_overlap >= 0.72 or quality < float(minimum_quality):
            continue
        boxes.append((box, quality, text_overlap, ink_ratio))
    merged = _merge_boxes([item[0] for item in boxes], gap=int(merge_gap))
    output = []
    for box in merged:
        quality, text_overlap, ink_ratio = _candidate_quality(
            box,
            width=width,
            height=height,
            text_boxes=normalized_text_boxes,
            ink_ratio=float(cv2.countNonZero(connected[box[1] : box[3], box[0] : box[2]]))
            / max(1.0, float((box[2] - box[0]) * (box[3] - box[1]))),
            border_margin=int(border_margin),
        )
        output.append(
            {
                "bbox": box,
                "area_ratio": ((box[2] - box[0]) * (box[3] - box[1])) / page_area,
                "quality_score": round(quality, 4),
                "text_overlap_ratio": round(text_overlap, 4),
                "ink_ratio": round(ink_ratio, 4),
                "detector": "opencv_non_text_v2",
            }
        )
    return sorted(output, key=lambda item: (item["bbox"][1], item["bbox"][0]))


def crop_visual_regions(
    image_path: str | Path,
    regions: list[dict[str, Any]],
    output_dir: str | Path,
    *,
    name_prefix: str,
    margin: int = 12,
) -> list[dict[str, Any]]:
    source = Path(image_path)
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        width, height = image.size
        outputs = []
        for index, region in enumerate(regions, start=1):
            bbox = region.get("bbox") or []
            if len(bbox) < 4:
                continue
            x0, y0, x1, y1 = [int(round(value)) for value in bbox[:4]]
            crop_box = [
                max(0, x0 - margin),
                max(0, y0 - margin),
                min(width, x1 + margin),
                min(height, y1 + margin),
            ]
            if crop_box[2] <= crop_box[0] or crop_box[3] <= crop_box[1]:
                continue
            filename = f"{name_prefix}_{index:02d}.png"
            target = target_dir / filename
            image.crop(tuple(crop_box)).save(target, format="PNG")
            outputs.append({**region, "crop_bbox": crop_box, "source_path": str(target), "original_file_name": filename})
    return outputs


def recrop_visual_region(
    image_path: str | Path,
    bbox: list[float] | tuple[float, ...],
    output_path: str | Path,
    *,
    margin: int = 0,
) -> dict[str, Any]:
    """Regenerate one crop after a reviewer adjusts its rectangle."""
    source = Path(image_path)
    target = Path(output_path)
    with Image.open(source) as image:
        width, height = image.size
        raw = normalize_region_bbox(bbox, width, height)
        if not raw:
            raise ValueError("裁剪框无效或区域过小")
        x0, y0, x1, y1 = raw
        crop_box = [max(0, x0 - margin), max(0, y0 - margin), min(width, x1 + margin), min(height, y1 + margin)]
        target.parent.mkdir(parents=True, exist_ok=True)
        image.crop(tuple(crop_box)).save(target, format="PNG")
        return {"bbox": raw, "crop_bbox": crop_box, "source_path": str(target), "width": crop_box[2] - crop_box[0], "height": crop_box[3] - crop_box[1]}


def merge_visual_regions(
    image_path: str | Path,
    regions: list[dict[str, Any]],
    output_path: str | Path,
    *,
    margin: int = 12,
) -> dict[str, Any]:
    """Merge selected regions from one page into a single ordered crop."""
    source = Path(image_path)
    target = Path(output_path)
    with Image.open(source) as image:
        width, height = image.size
        boxes = [normalize_region_bbox(item.get("bbox") or item.get("crop_bbox") or [], width, height) for item in regions]
        boxes = [box for box in boxes if box]
        if not boxes:
            raise ValueError("没有可合并的有效裁剪区域")
        x0 = max(0, min(box[0] for box in boxes) - margin)
        y0 = max(0, min(box[1] for box in boxes) - margin)
        x1 = min(width, max(box[2] for box in boxes) + margin)
        y1 = min(height, max(box[3] for box in boxes) + margin)
        target.parent.mkdir(parents=True, exist_ok=True)
        image.crop((x0, y0, x1, y1)).save(target, format="PNG")
        return {"bbox": [x0, y0, x1, y1], "source_path": str(target), "width": x1 - x0, "height": y1 - y0, "merged_count": len(boxes)}
