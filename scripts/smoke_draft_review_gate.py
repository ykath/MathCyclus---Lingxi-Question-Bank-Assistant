"""Verify the human approval and content-version gate on a temporary database."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DB = ROOT / "data" / "mathcyclus.sqlite3"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.import_service import (
    approve_draft_for_commit,
    commit_draft_to_question,
    create_manual_entry_draft,
    get_draft_question,
    update_draft_question_fields,
    list_draft_review_events,
)
from services.schema_migration_service import apply_pending_migrations


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="mathcyclus_review_gate_smoke_") as temp_dir:
        db_path = Path(temp_dir) / SOURCE_DB.name
        shutil.copy2(SOURCE_DB, db_path)
        apply_pending_migrations(str(db_path), apply=True, backup=False, allow_external_database=True)

        created = create_manual_entry_draft(
            str(db_path),
            {"source_item_id": "review-gate", "stem_tex": r"$x=1$", "review_status": "ready"},
            stamp="review_gate",
        )
        draft_id = created["draft_id"]
        try:
            commit_draft_to_question(str(db_path), draft_id)
        except ValueError as exc:
            assert "approved" in str(exc)
        else:
            raise AssertionError("unapproved draft was committed")

        approval = approve_draft_for_commit(str(db_path), draft_id, operator="smoke_reviewer")
        assert approval["status"] == "approved"

        update_draft_question_fields(
            str(db_path), draft_id, {"stem_tex": r"$x=2$"}, operator="smoke_editor"
        )
        changed = get_draft_question(str(db_path), draft_id)
        assert changed["review_status"] == "needs_review"
        assert not changed["approved_content_hash"]
        try:
            commit_draft_to_question(str(db_path), draft_id)
        except ValueError as exc:
            assert "approved" in str(exc) or "二次审核" in str(exc)
        else:
            raise AssertionError("edited draft was committed with stale approval")

        events = list_draft_review_events(str(db_path), draft_id=draft_id)
        decisions = {(item["decision"], item["to_status"]) for item in events}
        assert ("approve", "approved") in decisions
        assert ("edit", "needs_review") in decisions

    print("draft_review_gate_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
