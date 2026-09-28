"""Smoke test the optional Laya adapter without installing Laya."""

from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.laya_decision_service import choose_candidate, decide_choice, laya_status


def main() -> int:
    os.environ.pop("LAYA_ENABLED", None)
    status = laya_status()
    fallback = decide_choice(
        {"text": "一道函数题"},
        {"函数": "函数与方程", "几何": "平面几何"},
        "判断题目的主要知识板块。",
    )
    selected = choose_candidate(
        {"text": "2024 全国 I 卷第 12 题"},
        [{"id": "paper_1", "text": "2024 全国 I 卷"}],
        "选择最匹配的试卷来源。",
    )
    checks = {
        "status_shape": {"enabled", "installed", "available", "reason"}.issubset(status),
        "disabled_fallback": fallback["status"] == "fallback",
        "candidate_fallback": selected["status"] == "fallback" and selected["candidate"] is None,
        "no_database_write_contract": "writes_database" not in fallback,
    }
    for name, ok in checks.items():
        print(f"{name}={'ok' if ok else 'failed'}")
    print(f"status={'ok' if all(checks.values()) else 'failed'}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
