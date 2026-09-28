"""Smoke test the centralized parser capability report."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.runtime_capability_service import capability_warnings, runtime_capabilities


def main() -> None:
    report = runtime_capabilities()
    assert report.get("preferred_parser") in {"mineru_cloud", "mineru", "pymupdf"}
    assert isinstance(report.get("capabilities"), list)
    assert isinstance(capability_warnings(report), list)
    assert any(item.get("name") == "OpenCV" for item in report["capabilities"])
    print("runtime_capability_service_smoke=ok")


if __name__ == "__main__":
    main()
