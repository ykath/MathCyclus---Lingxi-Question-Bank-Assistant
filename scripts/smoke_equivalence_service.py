"""Smoke test for manually confirming a similarity relation."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.database_service import readonly_database_connection
from services.equivalence_service import (
    list_equivalence_events,
    list_question_equivalence_relations,
    update_equivalence_relation,
    upsert_manual_equivalence,
)
from services.import_service import approve_draft_for_commit, commit_draft_to_question, create_manual_entry_draft
from services.schema_migration_service import apply_pending_migrations


def main() -> None:
    source_db = ROOT / "data" / "mathcyclus.sqlite3"
    with tempfile.TemporaryDirectory(prefix="mathcyclus_equivalence_smoke_") as temp_dir:
        db_path = Path(temp_dir) / source_db.name
        shutil.copy2(source_db, db_path)
        apply_pending_migrations(str(db_path), apply=True, backup=False, allow_external_database=True)
        with readonly_database_connection(str(db_path)) as conn:
            ids = [str(row[0]) for row in conn.execute(
                "SELECT question_id FROM question ORDER BY question_id LIMIT 2"
            ).fetchall()]
        assert len(ids) == 2
        relation = upsert_manual_equivalence(
            str(db_path), ids[1], ids[0], relation_type="similar_question", confidence=0.91,
            note="smoke test",
        )
        assert relation["question_id_a"] == min(ids)
        assert relation["question_id_b"] == max(ids)
        with readonly_database_connection(str(db_path)) as conn:
            row = conn.execute(
                "SELECT relation_type, review_status, confidence FROM question_equivalence "
                "WHERE equivalence_id = ?",
                (relation["equivalence_id"],),
            ).fetchone()
        assert row and row[0] == "similar_question" and row[1] == "approved" and row[2] == 0.91
        listed = list_question_equivalence_relations(str(db_path), ids[0])
        assert listed and listed[0]["counterpart_question_id"] == ids[1]
        updated = update_equivalence_relation(
            str(db_path), relation["equivalence_id"], review_status="ignored", operator="smoke"
        )
        assert updated["review_status"] == "ignored"
        assert len(list_equivalence_events(str(db_path), relation["equivalence_id"])) == 2

        draft = create_manual_entry_draft(
            str(db_path),
            {
                "source_item_id": "relation-draft",
                "stem_tex": "这是一个用于关系提交测试的题干，长度足够进行审核。",
                "question_type_id": 5,
                "extra": {
                    "manual_equivalence_candidates": [{
                        "question_id": ids[0],
                        "relation_type": "similar_question",
                        "confidence": 0.87,
                        "note": "录入页勾选测试",
                    }],
                },
            },
        )
        approve_draft_for_commit(str(db_path), draft["draft_id"], operator="smoke")
        committed = commit_draft_to_question(str(db_path), draft["draft_id"], operator="smoke")
        assert committed["equivalence_ids"]
        with readonly_database_connection(str(db_path)) as conn:
            row = conn.execute(
                "SELECT review_status, relation_type FROM question_equivalence WHERE equivalence_id = ?",
                (committed["equivalence_ids"][0],),
            ).fetchone()
        assert row and row[0] == "approved" and row[1] == "similar_question"
    print("equivalence_service_smoke=ok")


if __name__ == "__main__":
    main()
