"""Smoke test the non-blocking structured question quality audit."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.question_quality_service import audit_question_bank
from services.schema_migration_service import apply_pending_migrations


def main() -> None:
    source = ROOT / "data" / "mathcyclus.sqlite3"
    with tempfile.TemporaryDirectory(prefix="mathcyclus_quality_smoke_") as temp_dir:
        target = Path(temp_dir) / source.name
        shutil.copy2(source, target)
        apply_pending_migrations(str(target), apply=True, backup=False, allow_external_database=True)
        report = audit_question_bank(str(target), limit=3)
        assert report["audited"] <= 3
        assert isinstance(report["counts"], dict)
        assert all(row.get("status") in {"ok", "warning", "blocker"} for row in report["rows"])
    print("question_quality_service_smoke=ok")


if __name__ == "__main__":
    main()
