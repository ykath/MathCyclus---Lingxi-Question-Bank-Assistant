"""Shared local similarity rules for duplicate detection and recommendations.

The thresholds and score shape follow the GaokaoWeb bind-similar algorithm.
This module deliberately has no database or UI dependency so every import path
can use the same result, including offline installations.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from typing import Any


SIM_MIN_LEN = 12
SIM_MAX_LEN_RATIO = 8.0
SIM_CHOICE_TYPES = {1, 2, 11, 12}
SIM_MAIN_THRESHOLD = 0.60
SIM_SUB_THRESHOLD = 0.40
SIM_PREFIX_THRESHOLD = 0.55

# Commands whose mathematical meaning must survive normalization. Removing
# these commands would make e.g. ``\\cap`` and ``\\cup`` falsely identical.
SENSITIVE_LATEX_COMMANDS = {
    "cap", "cup", "in", "notin", "subset", "subseteq", "supset", "supseteq",
    "parallel", "perp", "le", "leq", "ge", "geq", "neq", "ne", "approx",
    "sim", "equiv", "cong", "infty", "pm", "mp", "times", "cdot", "div",
}

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_COMMAND_RE = re.compile(r"\\([A-Za-z@]+)")
_IMAGE_COMMAND_RE = re.compile(
    r"\\(?:includegraphics|questionasset|includeimage|asset)\s*"
    r"(?:\[[^\]]*\])?\s*(?:\{[^{}]*\})?",
    re.IGNORECASE,
)
_IMAGE_ENV_RE = re.compile(
    r"\\begin\{(?:figure|centerimage|image)\}[\s\S]*?\\end\{(?:figure|centerimage|image)\}",
    re.IGNORECASE,
)
_LAYOUT_COMMAND_RE = re.compile(
    r"\\(?:underline|hspace|vspace|rule|makebox|mbox)\*?\s*"
    r"(?:\[[^\]]*\])?\s*\{[^{}]*\}",
    re.IGNORECASE,
)
_COMMENT_RE = re.compile(r"(?m)(?<!\\)%[^\r\n]*$")
_SUBQUESTION_RE = re.compile(r"(?=(?:\s*[（(]\s*\d+\s*[）)]|\s*\\item\b))")


def _choice_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, dict):
        return [str(value[key]).strip() for key in sorted(value) if str(value[key]).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [text]
        return _choice_values(parsed)
    return [str(value).strip()] if str(value).strip() else []


def normalize_similarity_text(value: Any) -> tuple[str, int]:
    """Return normalized text and the number of image placeholders.

    Image paths are intentionally discarded, but image presence is preserved.
    This prevents a text-only question from being marked exact with a diagram
    question while keeping renamed assets equivalent.
    """
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = _COMMENT_RE.sub("", text)
    image_count = 0

    def replace_image(match: re.Match) -> str:
        nonlocal image_count
        image_count += 1
        return " IMAGE "

    text = _IMAGE_ENV_RE.sub(replace_image, text)
    text = _IMAGE_COMMAND_RE.sub(replace_image, text)
    text = _LAYOUT_COMMAND_RE.sub(" ", text)
    text = re.sub(r"\\(?:begin|end)\s*\{[^{}]*\}", " ", text)
    text = _COMMAND_RE.sub(
        lambda match: f" {match.group(1).lower()} "
        if match.group(1).lower() in SENSITIVE_LATEX_COMMANDS
        else " ",
        text,
    )
    # Keep operators and formula markers, remove layout punctuation. The
    # placeholder is alphabetic so it remains visible after this step.
    text = re.sub(r"[{}()（）\[\]．。，,；;：:、\\]", " ", text)
    text = re.sub(r"\s+", "", text)
    return text.strip(), image_count


def extract_similarity_payload(
    stem: Any,
    choices: Any = None,
    question_type_id: Any = None,
) -> dict[str, Any]:
    """Prepare stem/full text and lightweight features for one question."""
    choice_values = _choice_values(choices)
    try:
        type_id = int(question_type_id) if question_type_id not in (None, "") else None
    except (TypeError, ValueError):
        type_id = None
    stem_norm, image_count = normalize_similarity_text(stem)
    full_raw = str(stem or "")
    if type_id in SIM_CHOICE_TYPES or choice_values:
        full_raw = "\n".join([full_raw, *choice_values])
    full_norm, full_image_count = normalize_similarity_text(full_raw)
    return {
        "stem_raw": str(stem or ""),
        "full_raw": full_raw,
        "stem_norm": stem_norm,
        "full_norm": full_norm,
        "image_count": image_count,
        "full_image_count": full_image_count,
        "choices": choice_values,
        "question_type_id": type_id,
    }


def _bigrams(value: str) -> set[str]:
    return {value[index:index + 2] for index in range(len(value) - 1)} if len(value) >= 2 else set()


def _bigram_stats(left: str, right: str) -> tuple[int, float, float]:
    left_set, right_set = _bigrams(left), _bigrams(right)
    if not left_set or not right_set:
        return 0, 0.0, 0.0
    intersection = len(left_set & right_set)
    union = len(left_set | right_set)
    containment = intersection / min(len(left_set), len(right_set))
    return intersection, intersection / union, containment


def _lcs_length(left: str, right: str) -> int:
    if not left or not right:
        return 0
    if len(left) > len(right):
        left, right = right, left
    # A bounded fallback keeps a malformed, extremely large draft from
    # blocking the Streamlit process while preserving the normal exact rule.
    if len(left) * len(right) > 12_000_000:
        common = Counter(left) & Counter(right)
        return sum(common.values())
    previous = [0] * (len(left) + 1)
    for right_char in right:
        current = [0]
        for index, left_char in enumerate(left, start=1):
            if left_char == right_char:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(previous[index], current[-1]))
        previous = current
    return previous[-1]


def _ratio_cover(left: str, right: str) -> tuple[float, float]:
    if not left or not right:
        return 0.0, 0.0
    lcs = _lcs_length(left, right)
    return 2.0 * lcs / (len(left) + len(right)), lcs / min(len(left), len(right))


def _number_agreement(left: str, right: str) -> float:
    left_numbers = {item for item in _NUMBER_RE.findall(left) if float(item) >= 4}
    right_numbers = {item for item in _NUMBER_RE.findall(right) if float(item) >= 4}
    if not left_numbers and not right_numbers:
        return 1.0
    if not left_numbers or not right_numbers:
        return 0.0
    common = left_numbers & right_numbers
    union = left_numbers | right_numbers
    return 0.7 * len(common) / len(union) + 0.3 * (1 - 0.5 ** len(common))


def _mode_score(left_norm: str, right_norm: str, left_raw: str, right_raw: str) -> dict[str, Any] | None:
    if min(len(left_norm), len(right_norm)) < SIM_MIN_LEN:
        return None
    if max(len(left_norm), len(right_norm)) / min(len(left_norm), len(right_norm)) > SIM_MAX_LEN_RATIO:
        return None
    intersection, jaccard, containment = _bigram_stats(left_norm, right_norm)
    if intersection < 6 or (jaccard < 0.4 and containment < 0.8):
        return None
    ratio, cover = _ratio_cover(left_norm, right_norm)
    numf = _number_agreement(left_raw, right_raw)
    adjusted = ratio * (0.6 + 0.4 * numf)
    template_left = _NUMBER_RE.sub("#", left_norm)
    template_right = _NUMBER_RE.sub("#", right_norm)
    template_score, _ = _ratio_cover(template_left, template_right)
    return {
        "score": adjusted,
        "ratio": ratio,
        "cover": cover,
        "numf": numf,
        "bigram_intersection": intersection,
        "bigram_jaccard": jaccard,
        "bigram_containment": containment,
        "template_score": template_score,
    }


def _prefix_parts(raw: str) -> list[str]:
    parts = [part.strip() for part in _SUBQUESTION_RE.split(str(raw or "")) if part.strip()]
    return parts if len(parts) >= 2 else []


def _prefix_score(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any] | None:
    left_parts, right_parts = _prefix_parts(left["stem_raw"]), _prefix_parts(right["stem_raw"])
    if not left_parts or not right_parts:
        return None
    if len(left_parts) > len(right_parts):
        left_parts, right_parts = right_parts, left_parts
    left_raw = "\n".join(left_parts)
    right_raw = "\n".join(right_parts[: len(left_parts)])
    left_norm, _ = normalize_similarity_text(left_raw)
    right_norm, _ = normalize_similarity_text(right_raw)
    whole = _mode_score(left_norm, right_norm, left_raw, right_raw)
    if whole and whole["score"] >= SIM_PREFIX_THRESHOLD:
        whole = dict(whole)
        whole["channel"] = "前缀子题"
        return whole
    if len(left_parts) < 2:
        return None
    left_questions = "".join(left_parts[1:])
    right_questions = "".join(right_parts[1:len(left_parts)])
    left_q_norm, _ = normalize_similarity_text(left_questions)
    right_q_norm, _ = normalize_similarity_text(right_questions)
    if min(len(left_q_norm), len(right_q_norm)) < 6:
        return None
    question_ratio, _ = _ratio_cover(left_q_norm, right_q_norm)
    condition_left, _ = normalize_similarity_text(left_parts[0])
    condition_right, _ = normalize_similarity_text(right_parts[0])
    condition_ratio, _ = _ratio_cover(condition_left, condition_right)
    if question_ratio >= 0.85 and condition_ratio >= 0.35:
        return {
            "score": question_ratio,
            "ratio": question_ratio,
            "cover": 1.0,
            "numf": _number_agreement(left_questions, right_questions),
            "bigram_intersection": 0,
            "bigram_jaccard": 0.0,
            "bigram_containment": 0.0,
            "template_score": question_ratio,
            "channel": "前缀子题",
        }
    return None


def score_question_pair(
    left_stem: Any,
    right_stem: Any,
    *,
    left_choices: Any = None,
    right_choices: Any = None,
    left_question_type_id: Any = None,
    right_question_type_id: Any = None,
    allow_sub: bool = False,
) -> dict[str, Any]:
    """Score one pair using the shared GaokaoWeb-compatible rule set."""
    left = extract_similarity_payload(left_stem, left_choices, left_question_type_id)
    right = extract_similarity_payload(right_stem, right_choices, right_question_type_id)
    exact = (
        left["stem_norm"]
        and left["stem_norm"] == right["stem_norm"]
        and left["image_count"] == right["image_count"]
    )
    if exact:
        return {
            "score": 1.0, "base_score": 1.0, "channel": "完全相同", "kind": "exact",
            "ratio": 1.0, "cover": 1.0, "numf": 1.0, "template_score": 1.0,
            "bigram_jaccard": 1.0, "bigram_containment": 1.0,
            "choice_mode": "stem", "reasons": ["题干归一化后完全一致"], "warnings": [],
        }
    candidates: list[dict[str, Any]] = []
    stem_score = _mode_score(left["stem_norm"], right["stem_norm"], left["stem_raw"], right["stem_raw"])
    if stem_score:
        stem_score["choice_mode"] = "stem"
        candidates.append(stem_score)
    if left["choices"] or right["choices"] or left["question_type_id"] in SIM_CHOICE_TYPES or right["question_type_id"] in SIM_CHOICE_TYPES:
        full_score = _mode_score(left["full_norm"], right["full_norm"], left["full_raw"], right["full_raw"])
        if full_score:
            full_score["choice_mode"] = "stem+choices"
            candidates.append(full_score)
    prefix_score = _prefix_score(left, right)
    if prefix_score:
        prefix_score["choice_mode"] = "stem"
        candidates.append(prefix_score)
    if candidates:
        best = max(candidates, key=lambda item: (item["score"], item.get("channel") == "前缀子题"))
        channel = best.get("channel") or ("主通道" if best["score"] >= SIM_MAIN_THRESHOLD else "")
        if not channel and allow_sub and best["score"] >= SIM_SUB_THRESHOLD and best["cover"] >= 0.7 and best["bigram_containment"] >= 0.7:
            channel = "疑似小问"
        if not channel:
            channel = "备选"
        result = dict(best)
        result.update({
            "base_score": best["score"], "score": best["score"], "channel": channel,
            "kind": "similar", "reasons": [], "warnings": [],
        })
        if best["numf"] < 0.5:
            result["warnings"].append("数字不完全一致")
            result["reasons"].append("题型结构接近但数字存在差异")
        if best["template_score"] > best["ratio"] + 0.12:
            result["reasons"].append("去数字后的题型结构接近")
        if not result["reasons"]:
            result["reasons"].append("题干结构接近")
        return result
    return {
        "score": None, "base_score": None, "channel": "无法计算", "kind": "none",
        "ratio": 0.0, "cover": 0.0, "numf": None, "template_score": None,
        "bigram_jaccard": 0.0, "bigram_containment": 0.0,
        "choice_mode": "stem", "reasons": [],
        "warnings": ["题目过短、长度差异过大或未通过双字预筛"],
    }


def similarity_score(left_stem: Any, right_stem: Any, **kwargs: Any) -> float | None:
    """Convenience wrapper used by callers that only need a numeric score."""
    return score_question_pair(left_stem, right_stem, **kwargs).get("score")
