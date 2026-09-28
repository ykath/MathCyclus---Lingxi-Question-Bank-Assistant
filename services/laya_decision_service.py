"""Optional local Laya adapter for fast typed decisions.

Laya is deliberately kept outside the core dependency set. This adapter makes
classification and candidate selection available when the package and model
are installed, while returning an explicit fallback result otherwise.
"""

from __future__ import annotations

import importlib.util
import os
from functools import lru_cache
from typing import Any, Iterable


DEFAULT_MODEL = "multilingual"
DEFAULT_MIN_CONFIDENCE = 0.80


def _env_flag(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def laya_config() -> dict[str, Any]:
    raw_confidence = os.getenv("LAYA_MIN_CONFIDENCE", str(DEFAULT_MIN_CONFIDENCE))
    try:
        min_confidence = max(0.0, min(1.0, float(raw_confidence)))
    except (TypeError, ValueError):
        min_confidence = DEFAULT_MIN_CONFIDENCE
    return {
        "enabled": _env_flag(os.getenv("LAYA_ENABLED")),
        "model": str(os.getenv("LAYA_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        "min_confidence": min_confidence,
    }


def laya_installed() -> bool:
    try:
        return importlib.util.find_spec("laya") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def laya_status() -> dict[str, Any]:
    config = laya_config()
    installed = laya_installed()
    if not config["enabled"]:
        reason = "disabled"
    elif not installed:
        reason = "package_not_installed"
    else:
        reason = "ready"
    return {
        "enabled": bool(config["enabled"]),
        "installed": installed,
        "available": bool(config["enabled"] and installed),
        "model": config["model"],
        "min_confidence": config["min_confidence"],
        "reason": reason,
    }


@lru_cache(maxsize=2)
def _router(model: str):
    from laya import Router

    return Router(default=model)


def _confidence(answer: Any) -> float | None:
    if not isinstance(answer, dict):
        return None
    value = answer.get("confidence")
    if value is None:
        value = answer.get("probability")
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def decide_choice(
    state: Any,
    criteria: dict[str, str],
    instructions: str,
    *,
    decision_name: str = "decision",
    min_confidence: float | None = None,
) -> dict[str, Any]:
    """Choose one fixed label without changing project data.

    Callers must treat ``uncertain`` and all fallback statuses as reviewable;
    this service never writes a question, source, or topic to the database.
    """
    normalized = {
        str(label).strip(): str(description).strip()
        for label, description in (criteria or {}).items()
        if str(label).strip()
    }
    if not normalized:
        return {"status": "invalid", "reason": "no_candidates", "choice": "", "confidence": None}
    status = laya_status()
    if not status["available"]:
        return {
            "status": "fallback",
            "reason": status["reason"],
            "choice": "",
            "confidence": None,
            "candidates": list(normalized),
        }
    threshold = status["min_confidence"] if min_confidence is None else max(0.0, min(1.0, float(min_confidence)))
    try:
        result = _router(status["model"]).predict(
            state,
            {
                decision_name: {
                    "type": "choice",
                    "instructions": str(instructions or "Choose the best matching option."),
                    "criteria": normalized,
                }
            },
        )
        answer = ((result or {}).get("answers") or {}).get(decision_name) or {}
        choice = str(answer.get("choice") or "").strip()
        confidence = _confidence(answer)
        accepted = bool(choice) and (confidence is None or confidence >= threshold)
        return {
            "status": "accepted" if accepted else "uncertain",
            "reason": "ok" if accepted else "low_confidence_or_empty",
            "choice": choice,
            "confidence": confidence,
            "model": status["model"],
            "raw": result,
        }
    except Exception as exc:
        return {
            "status": "fallback",
            "reason": f"laya_error:{type(exc).__name__}",
            "error": str(exc),
            "choice": "",
            "confidence": None,
        }


def choose_candidate(
    state: Any,
    candidates: Iterable[dict[str, Any]],
    instructions: str,
    *,
    candidate_id_key: str = "id",
    candidate_text_key: str = "text",
    min_confidence: float | None = None,
) -> dict[str, Any]:
    """Select one source/topic/question candidate from a bounded candidate list."""
    candidate_rows = [item for item in candidates if isinstance(item, dict)]
    criteria = {
        str(item.get(candidate_id_key) or "").strip(): str(item.get(candidate_text_key) or "").strip()
        for item in candidate_rows
        if str(item.get(candidate_id_key) or "").strip()
    }
    result = decide_choice(
        state,
        criteria,
        instructions,
        min_confidence=min_confidence,
    )
    choice = result.get("choice") or ""
    result["candidate"] = next((item for item in candidate_rows if str(item.get(candidate_id_key) or "").strip() == choice), None)
    return result
