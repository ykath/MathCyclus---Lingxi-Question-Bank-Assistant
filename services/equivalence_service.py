"""Helpers for same-question relations and manual review decision files."""

from __future__ import annotations

import csv
import hashlib
import json
import uuid
from collections import Counter
from pathlib import Path

from services.database_service import BASE_DIR, database_connection, readonly_database_connection


PROJECT_ROOT = Path(BASE_DIR)
DEFAULT_DECISIONS_PATH = PROJECT_ROOT / "db" / "seed" / "equivalence_review_decisions_20260902_initial.csv"
SUPPORTED_DECISIONS = {"pending", "keep_all", "mark_equivalent", "merge_to_canonical", "ignore"}
SUPPORTED_RELATION_TYPES = {"same_question", "similar_question", "variant"}
SUPPORTED_RELATION_SOURCES = {"manual", "similarity_review", "draft_import", "historical_migration", "api"}


def resolve_path(path: str | Path | None = None) -> Path:
    target = Path(path) if path else DEFAULT_DECISIONS_PATH
    if not target.is_absolute():
        target = PROJECT_ROOT / target
    return target.resolve()


def split_pipe_list(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split("|") if item.strip()]


def list_review_decisions(path: str | Path | None = None) -> list[dict]:
    """Load the manual equivalence-review CSV as dictionaries."""
    decisions_path = resolve_path(path)
    if not decisions_path.exists():
        return []

    with decisions_path.open(encoding="utf-8-sig", newline="") as file:
        rows = []
        for row in csv.DictReader(file):
            normalized = {key: (value or "").strip() for key, value in row.items()}
            normalized["question_id_list"] = split_pipe_list(normalized.get("question_ids", ""))
            normalized["chapter_list"] = split_pipe_list(normalized.get("chapters", ""))
            rows.append(normalized)
    return rows


def summarize_review_decisions(path: str | Path | None = None) -> dict:
    """Return counts for the current equivalence-review decision CSV."""
    rows = list_review_decisions(path)
    decision_counts = Counter(row.get("decision", "") for row in rows)
    issue_counts = Counter(row.get("issue_type", "") for row in rows)
    unsupported = [
        row
        for row in rows
        if row.get("decision", "") not in SUPPORTED_DECISIONS
    ]
    return {
        "total": len(rows),
        "decision_counts": dict(sorted(decision_counts.items())),
        "issue_counts": dict(sorted(issue_counts.items())),
        "unsupported_decision_rows": len(unsupported),
    }


def list_equivalence_relations(
    db_path: str | None = None,
    review_status: str = "",
    relation_type: str = "",
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """List same-question relation rows with lightweight source context."""
    safe_limit = max(1, min(int(limit or 50), 200))
    safe_offset = max(0, int(offset or 0))
    clauses: list[str] = []
    params: list[object] = []

    if review_status:
        clauses.append("qe.review_status = ?")
        params.append(review_status)
    if relation_type:
        clauses.append("qe.relation_type = ?")
        params.append(relation_type)

    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.extend([safe_limit, safe_offset])

    sql = f"""
        SELECT
            qe.equivalence_id,
            qe.question_id_a,
            qe.question_id_b,
            qe.relation_type,
            qe.confidence,
            qe.review_status,
            qe.note,
            qe.relation_source,
            qe.created_at,
            qe.updated_at,
            la.legacy_id AS legacy_id_a,
            la.legacy_file_path AS legacy_file_path_a,
            la.detected_year AS year_a,
            la.detected_source AS source_a,
            la.detected_question_number AS number_a,
            la.detected_chapter AS chapter_a,
            lb.legacy_id AS legacy_id_b,
            lb.legacy_file_path AS legacy_file_path_b,
            lb.detected_year AS year_b,
            lb.detected_source AS source_b,
            lb.detected_question_number AS number_b,
            lb.detected_chapter AS chapter_b
        FROM question_equivalence qe
        LEFT JOIN legacy_question_map la ON la.question_id = qe.question_id_a
        LEFT JOIN legacy_question_map lb ON lb.question_id = qe.question_id_b
        {where_sql}
        ORDER BY qe.review_status, qe.relation_type, qe.confidence DESC, qe.question_id_a
        LIMIT ? OFFSET ?
    """
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def list_question_equivalence_relations(
    db_path: str | None = None,
    question_id: str = "",
    *,
    review_status: str = "",
    limit: int = 100,
) -> list[dict]:
    """List active or historical relations touching one question."""
    question_id = str(question_id or "").strip()
    if not question_id:
        return []
    safe_limit = max(1, min(int(limit or 100), 500))
    clauses = ["(qe.question_id_a = ? OR qe.question_id_b = ?)"]
    params: list[object] = [question_id, question_id]
    if review_status:
        clauses.append("qe.review_status = ?")
        params.append(review_status)
    params.append(safe_limit)
    sql = f"""
        SELECT qe.*,
               CASE WHEN qe.question_id_a = ? THEN qe.question_id_b ELSE qe.question_id_a END AS counterpart_question_id
        FROM question_equivalence qe
        WHERE {' AND '.join(clauses)}
        ORDER BY CASE qe.review_status WHEN 'approved' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,
                 qe.updated_at DESC, qe.equivalence_id
        LIMIT ?
    """
    params.insert(0, question_id)
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            counterpart = conn.execute(
                "SELECT question_id, stem_tex, choices_json FROM question WHERE question_id = ?",
                (row["counterpart_question_id"],),
            ).fetchone()
            row["counterpart"] = dict(counterpart) if counterpart else {}
    return result


def list_equivalence_events(
    db_path: str | None = None,
    equivalence_id: str = "",
    limit: int = 50,
) -> list[dict]:
    safe_limit = max(1, min(int(limit or 50), 200))
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM question_equivalence_event WHERE equivalence_id = ? "
            "ORDER BY created_at DESC, event_id DESC LIMIT ?",
            (str(equivalence_id or ""), safe_limit),
        ).fetchall()
    return [dict(row) for row in rows]


def record_equivalence_event_from_conn(
    conn,
    equivalence_id: str,
    *,
    action: str,
    before_status: str = "",
    after_status: str = "",
    before_relation_type: str = "",
    after_relation_type: str = "",
    relation_source: str = "manual",
    operator: str = "",
    note: str = "",
    detail: dict | None = None,
) -> str:
    """Append an equivalence audit event inside the caller's transaction."""
    event_id = "QEE" + uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO question_equivalence_event(
            event_id, equivalence_id, action, before_status, after_status,
            before_relation_type, after_relation_type, relation_source,
            operator, note, detail_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            str(equivalence_id or ""),
            str(action or "updated"),
            str(before_status or ""),
            str(after_status or ""),
            str(before_relation_type or ""),
            str(after_relation_type or ""),
            str(relation_source or "manual"),
            str(operator or ""),
            str(note or ""),
            json.dumps(detail or {}, ensure_ascii=False),
        ),
    )
    return event_id


def count_equivalence_relations(
    db_path: str | None = None,
    review_status: str = "",
    relation_type: str = "",
) -> int:
    """Count same-question relation rows."""
    clauses: list[str] = []
    params: list[object] = []
    if review_status:
        clauses.append("review_status = ?")
        params.append(review_status)
    if relation_type:
        clauses.append("relation_type = ?")
        params.append(relation_type)

    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
    with readonly_database_connection(db_path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM question_equivalence {where_sql}", params).fetchone()[0])


def upsert_manual_equivalence(
    db_path: str | None,
    question_id_a: str,
    question_id_b: str,
    *,
    relation_type: str = "similar_question",
    confidence: float | None = None,
    note: str = "",
    review_status: str = "approved",
    relation_source: str = "manual",
    operator: str = "",
) -> dict:
    """Persist one human-confirmed relation without merging either question."""
    left, right = sorted([str(question_id_a or "").strip(), str(question_id_b or "").strip()])
    if not left or not right:
        raise ValueError("两个题目 ID 都不能为空")
    if left == right:
        raise ValueError("不能把题目与自身建立关系")
    relation_type = str(relation_type or "similar_question").strip()
    if relation_type not in SUPPORTED_RELATION_TYPES:
        raise ValueError(f"不支持的关系类型：{relation_type}")
    review_status = str(review_status or "approved").strip()
    if review_status not in {"pending", "approved", "ignored"}:
        raise ValueError(f"不支持的审核状态：{review_status}")
    relation_source = str(relation_source or "manual").strip()
    if relation_source not in SUPPORTED_RELATION_SOURCES:
        raise ValueError(f"不支持的关系来源：{relation_source}")
    safe_confidence = None if confidence is None else max(0.0, min(1.0, float(confidence)))
    equivalence_id = "QE" + hashlib.sha1(
        f"{left}\u241f{right}\u241f{relation_type}".encode("utf-8")
    ).hexdigest()[:14]
    with database_connection(db_path) as conn:
        missing = conn.execute(
            "SELECT question_id FROM question WHERE question_id IN (?, ?)", (left, right)
        ).fetchall()
        found = {str(row[0]) for row in missing}
        if found != {left, right}:
            missing_ids = ", ".join(sorted({left, right} - found))
            raise ValueError(f"题目不存在：{missing_ids}")
        previous = conn.execute(
            "SELECT relation_type, confidence, review_status, note, relation_source FROM question_equivalence "
            "WHERE question_id_a = ? AND question_id_b = ? AND relation_type = ?",
            (left, right, relation_type),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO question_equivalence(
                equivalence_id, question_id_a, question_id_b, relation_type,
                confidence, review_status, note, relation_source, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(question_id_a, question_id_b, relation_type)
            DO UPDATE SET
                confidence = excluded.confidence,
                review_status = excluded.review_status,
                note = excluded.note,
                relation_source = excluded.relation_source,
                updated_at = CURRENT_TIMESTAMP
            """,
            (equivalence_id, left, right, relation_type, safe_confidence, review_status, str(note or "").strip(), relation_source),
        )
        action = "created" if previous is None else "updated"
        record_equivalence_event_from_conn(
            conn,
            equivalence_id,
            action=action,
            before_status=str(previous["review_status"] if previous else ""),
            after_status=review_status,
            before_relation_type=relation_type,
            after_relation_type=relation_type,
            relation_source=relation_source,
            operator=operator,
            note=str(note or "").strip(),
            detail={"question_id_a": left, "question_id_b": right},
        )
    return {
        "equivalence_id": equivalence_id,
        "question_id_a": left,
        "question_id_b": right,
        "relation_type": relation_type,
        "confidence": safe_confidence,
        "review_status": review_status,
        "relation_source": relation_source,
    }


def update_equivalence_relation(
    db_path: str | None,
    equivalence_id: str,
    *,
    review_status: str | None = None,
    relation_type: str | None = None,
    note: str | None = None,
    operator: str = "",
) -> dict:
    """Update a relation while keeping an immutable event trail."""
    allowed_statuses = {"pending", "approved", "ignored"}
    if review_status is not None and review_status not in allowed_statuses:
        raise ValueError(f"不支持的审核状态：{review_status}")
    if relation_type is not None and relation_type not in SUPPORTED_RELATION_TYPES:
        raise ValueError(f"不支持的关系类型：{relation_type}")
    equivalence_id = str(equivalence_id or "").strip()
    if not equivalence_id:
        raise ValueError("关系 ID 不能为空")
    with database_connection(db_path) as conn:
        current = conn.execute(
            "SELECT * FROM question_equivalence WHERE equivalence_id = ?",
            (equivalence_id,),
        ).fetchone()
        if current is None:
            raise ValueError(f"未找到题目关系：{equivalence_id}")
        before = dict(current)
        new_status = review_status if review_status is not None else before["review_status"]
        new_type = relation_type if relation_type is not None else before["relation_type"]
        new_note = str(note if note is not None else before["note"] or "").strip()
        if new_type != before["relation_type"]:
            conflict = conn.execute(
                "SELECT equivalence_id FROM question_equivalence WHERE question_id_a = ? AND question_id_b = ? AND relation_type = ? AND equivalence_id != ?",
                (before["question_id_a"], before["question_id_b"], new_type, equivalence_id),
            ).fetchone()
            if conflict:
                raise ValueError("该题目对已经存在目标关系类型，未执行修改")
        new_equivalence_id = "QE" + hashlib.sha1(
            f"{before['question_id_a']}\u241f{before['question_id_b']}\u241f{new_type}".encode("utf-8")
        ).hexdigest()[:14]
        conn.execute(
            "UPDATE question_equivalence SET equivalence_id = ?, review_status = ?, relation_type = ?, note = ?, updated_at = CURRENT_TIMESTAMP WHERE equivalence_id = ?",
            (new_equivalence_id, new_status, new_type, new_note, equivalence_id),
        )
        record_equivalence_event_from_conn(
            conn,
            new_equivalence_id,
            action="updated",
            before_status=before["review_status"],
            after_status=new_status,
            before_relation_type=before["relation_type"],
            after_relation_type=new_type,
            relation_source=before["relation_source"],
            operator=operator,
            note=new_note,
            detail={"previous_note": before["note"] or "", "previous_equivalence_id": equivalence_id},
        )
    return {**before, "equivalence_id": new_equivalence_id, "review_status": new_status, "relation_type": new_type, "note": new_note}
