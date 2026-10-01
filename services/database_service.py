#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MathEx 家长版 · SQLite 数据库服务层（M1 基础设施）

职责：
- 连接与初始化（首次自动建表，幂等）
- 题目 CRUD + 修订记录
- 题库检索 / 筛选 / 标签聚合
- AI/OCR 草稿生命周期（录入 → 审核 → 确认入库）
- 重复题检测（文本指纹 + 相似度，不引入语义索引）
- 首页统计

页面层不直接写 SQL，一律调用本模块。
"""
import difflib
import json
import os
import re
import sqlite3
import threading
from datetime import datetime

_LOCK = threading.Lock()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "mathcyclus.sqlite3")
SCHEMA_PATH = os.path.join(BASE_DIR, "db", "schema.sql")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ------------------------------------------------------------
# 连接与初始化
# ------------------------------------------------------------

def get_conn(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_initialized(db_path: str | None = None) -> None:
    """首次运行自动按 db/schema.sql 建表（幂等）。"""
    with _LOCK:
        conn = get_conn(db_path)
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='question'"
            ).fetchone()
            if row is None and os.path.exists(SCHEMA_PATH):
                with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
                    conn.executescript(f.read())
                conn.commit()
        finally:
            conn.close()


# ------------------------------------------------------------
# 题目 CRUD 与修订
# ------------------------------------------------------------

def next_question_id(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT question_id FROM question ORDER BY LENGTH(question_id) DESC, question_id DESC LIMIT 1"
    ).fetchone()
    if not row:
        return "Q000001"
    match = re.match(r"Q(\d+)", row["question_id"])
    seq = int(match.group(1)) + 1 if match else 1
    return f"Q{seq:06d}"


def _dump_json(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def insert_question(fields: dict, change_source: str = "manual", note: str = "",
                    db_path: str | None = None) -> str:
    """插入题目并写修订记录，返回 question_id。"""
    ensure_initialized(db_path)
    with _LOCK:
        conn = get_conn(db_path)
        try:
            qid = next_question_id(conn)
            conn.execute(
                """INSERT INTO question
                   (question_id, question_type_id, stem_tex, choices_json, answer_tex,
                    solution_tex, difficulty, tags_json, note, is_classic, official_flag,
                    canonical_tex, raw_source_tex, normalized_status,
                    created_at, updated_at, last_manual_edit_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    qid,
                    fields.get("question_type_id"),
                    fields.get("stem_tex", ""),
                    _dump_json(fields.get("choices")),
                    fields.get("answer_tex", ""),
                    fields.get("solution_tex", ""),
                    fields.get("difficulty"),
                    _dump_json(fields.get("tags")),
                    fields.get("note", ""),
                    int(bool(fields.get("is_classic", 0))),
                    int(bool(fields.get("official_flag", 0))),
                    fields.get("canonical_tex", ""),
                    fields.get("raw_source_tex", ""),
                    fields.get("normalized_status", "normalized"),
                    _now(), _now(), _now(),
                ),
            )
            conn.execute(
                """INSERT INTO question_revision
                   (question_id, change_source, changed_fields_json, before_json, after_json, operator, note, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (qid, change_source, "", "{}", _dump_json(fields), "parent", note, _now()),
            )
            conn.commit()
            return qid
        finally:
            conn.close()


QUESTION_EDITABLE_FIELDS = {
    "stem_tex": "题干", "choices": "选项", "answer_tex": "答案",
    "solution_tex": "解析", "difficulty": "难度", "tags": "知识点标签",
    "note": "备注", "is_classic": "经典题标记", "question_type_id": "题型",
}


def update_question(question_id: str, updates: dict, note: str = "",
                    db_path: str | None = None) -> bool:
    """更新题目字段并写修订记录（只记录实际变化的字段）。"""
    ensure_initialized(db_path)
    with _LOCK:
        conn = get_conn(db_path)
        try:
            row = conn.execute("SELECT * FROM question WHERE question_id=?", (question_id,)).fetchone()
            if not row:
                return False
            before = dict(row)
            column_map = {"choices": "choices_json", "tags": "tags_json"}
            changed, sets, params = [], [], []
            for key, value in updates.items():
                if key not in QUESTION_EDITABLE_FIELDS:
                    continue
                column = column_map.get(key, key)
                new_value = _dump_json(value) if key in ("choices", "tags") else value
                if key == "is_classic":
                    new_value = int(bool(value))
                if new_value != (before.get(column) or ""):
                    changed.append(key)
                    sets.append(f"{column}=?")
                    params.append(new_value)
            if not changed:
                return True
            sets.append("updated_at=?")
            sets.append("last_manual_edit_at=?")
            params.extend([_now(), _now(), question_id])
            conn.execute(f"UPDATE question SET {', '.join(sets)} WHERE question_id=?", params)
            conn.execute(
                """INSERT INTO question_revision
                   (question_id, change_source, changed_fields_json, before_json, after_json, operator, note, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    question_id, "manual", _dump_json(changed),
                    _dump_json({k: before.get(column_map.get(k, k)) for k in changed}),
                    _dump_json(updates), "parent", note, _now(),
                ),
            )
            conn.commit()
            return True
        finally:
            conn.close()


def get_question(question_id: str, db_path: str | None = None) -> dict | None:
    ensure_initialized(db_path)
    conn = get_conn(db_path)
    try:
        row = conn.execute("SELECT * FROM question WHERE question_id=?", (question_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["tags"] = json.loads(item["tags_json"]) if item.get("tags_json") else []
        item["choices"] = json.loads(item["choices_json"]) if item.get("choices_json") else []
        return item
    finally:
        conn.close()


def delete_question(question_id: str, db_path: str | None = None) -> bool:
    ensure_initialized(db_path)
    with _LOCK:
        conn = get_conn(db_path)
        try:
            cur = conn.execute("DELETE FROM question WHERE question_id=?", (question_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


# ------------------------------------------------------------
# 题库检索与筛选
# ------------------------------------------------------------

def search_questions(keyword: str = "", tags: list[str] | None = None,
                     difficulty: list[int] | None = None,
                     question_type_id: int | None = None,
                     is_classic: bool | None = None,
                     printed: bool | None = None,
                     page: int = 1, page_size: int = 10,
                     db_path: str | None = None) -> tuple[list[dict], int]:
    """组合筛选 + 分页，返回 (题目列表, 总数)。tags 为「全部包含」语义。"""
    ensure_initialized(db_path)
    conn = get_conn(db_path)
    try:
        where, params = ["1=1"], []
        if keyword:
            where.append("(stem_tex LIKE ? OR answer_tex LIKE ? OR solution_tex LIKE ? OR note LIKE ? OR question_id LIKE ?)")
            like = f"%{keyword}%"
            params.extend([like, like, like, like, like])
        if difficulty:
            where.append(f"difficulty IN ({','.join('?' * len(difficulty))})")
            params.extend(difficulty)
        if question_type_id:
            where.append("question_type_id=?")
            params.append(question_type_id)
        if is_classic is not None:
            where.append("is_classic=?")
            params.append(int(is_classic))
        if printed is True:
            where.append("EXISTS (SELECT 1 FROM print_job_item p WHERE p.question_id=question.question_id)")
        elif printed is False:
            where.append("NOT EXISTS (SELECT 1 FROM print_job_item p WHERE p.question_id=question.question_id)")
        where_sql = " AND ".join(where)

        rows = conn.execute(
            f"SELECT * FROM question WHERE {where_sql} ORDER BY updated_at DESC", params
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["tags"] = json.loads(item["tags_json"]) if item.get("tags_json") else []
            if tags and not all(t in item["tags"] for t in tags):
                continue
            items.append(item)
        total = len(items)
        start = (max(1, page) - 1) * page_size
        return items[start:start + page_size], total
    finally:
        conn.close()


def list_all_tags(db_path: str | None = None) -> list[str]:
    """聚合题库中全部知识点标签（按出现频次降序）。"""
    ensure_initialized(db_path)
    conn = get_conn(db_path)
    try:
        rows = conn.execute("SELECT tags_json FROM question WHERE tags_json != ''").fetchall()
        counter: dict[str, int] = {}
        for row in rows:
            try:
                for tag in json.loads(row["tags_json"] or "[]"):
                    counter[tag] = counter.get(tag, 0) + 1
            except json.JSONDecodeError:
                continue
        return [t for t, _ in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))]
    finally:
        conn.close()


def list_question_types(db_path: str | None = None) -> list[dict]:
    ensure_initialized(db_path)
    conn = get_conn(db_path)
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM question_type ORDER BY question_type_id").fetchall()]
    finally:
        conn.close()


# ------------------------------------------------------------
# 重复题检测（M1-T09）：归一化题干 + 相似度
# ------------------------------------------------------------

def _normalize_stem(text: str) -> str:
    text = re.sub(r"\\[a-zA-Z]+", "", text or "")     # 去 LaTeX 命令
    text = re.sub(r"[\s${}_\\^{}()（）,，.。;；:：]", "", text)
    return text


def find_similar_questions(stem_tex: str, threshold: float = 0.85,
                           db_path: str | None = None) -> list[dict]:
    """返回与给定题干相似的已有题目 [{question_id, ratio, stem_preview}]。"""
    ensure_initialized(db_path)
    target = _normalize_stem(stem_tex)
    if len(target) < 8:
        return []
    conn = get_conn(db_path)
    try:
        rows = conn.execute("SELECT question_id, stem_tex FROM question").fetchall()
        results = []
        for row in rows:
            candidate = _normalize_stem(row["stem_tex"])
            if not candidate:
                continue
            ratio = difflib.SequenceMatcher(None, target, candidate).ratio()
            if ratio >= threshold:
                results.append({
                    "question_id": row["question_id"],
                    "ratio": round(ratio, 3),
                    "stem_preview": (row["stem_tex"] or "")[:60],
                })
        return sorted(results, key=lambda x: -x["ratio"])
    finally:
        conn.close()


# ------------------------------------------------------------
# 导入批次与草稿（M1-T07/T08/T10）
# ------------------------------------------------------------

def create_import_batch(import_type: str, source_path: str = "", summary: str = "",
                        mode: str = "commit", db_path: str | None = None) -> int:
    ensure_initialized(db_path)
    with _LOCK:
        conn = get_conn(db_path)
        try:
            cur = conn.execute(
                "INSERT INTO import_batch (import_type, source_path, mode, summary) VALUES (?,?,?,?)",
                (import_type, source_path, mode, summary),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def finish_import_batch(batch_id: int, summary: str = "", db_path: str | None = None) -> None:
    with _LOCK:
        conn = get_conn(db_path)
        try:
            conn.execute("UPDATE import_batch SET finished_at=?, summary=? WHERE batch_id=?",
                         (_now(), summary, batch_id))
            conn.commit()
        finally:
            conn.close()


def add_report_item(batch_id: int, status: str, source_file: str = "",
                    question_id: str | None = None, reason: str = "",
                    db_path: str | None = None) -> None:
    with _LOCK:
        conn = get_conn(db_path)
        try:
            conn.execute(
                """INSERT INTO import_report_item (batch_id, source_file, question_id, status, reason, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (batch_id, source_file, question_id, status, reason, _now()),
            )
            conn.commit()
        finally:
            conn.close()


def insert_draft(fields: dict, batch_id: int | None = None,
                 db_path: str | None = None) -> int:
    ensure_initialized(db_path)
    with _LOCK:
        conn = get_conn(db_path)
        try:
            cur = conn.execute(
                """INSERT INTO question_import_draft
                   (batch_id, source_item_id, source_label, proposed_action, review_status,
                    question_type, stem_tex, choices_json, answer_tex, solution_tex,
                    difficulty, tags_json, note, raw_source_text, confidence_json, validation_json, extra_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    batch_id,
                    fields.get("source_item_id", ""),
                    fields.get("source_label", ""),
                    fields.get("proposed_action", "insert"),
                    fields.get("review_status", "needs_review"),
                    fields.get("question_type", ""),
                    fields.get("stem_tex", ""),
                    _dump_json(fields.get("choices")),
                    fields.get("answer_tex", ""),
                    fields.get("solution_tex", ""),
                    fields.get("difficulty"),
                    _dump_json(fields.get("tags")),
                    fields.get("note", ""),
                    fields.get("raw_source_text", ""),
                    _dump_json(fields.get("confidence")),
                    _dump_json(fields.get("validation")),
                    _dump_json(fields.get("extra")),
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def add_draft_asset(draft_id: int, file_path: str, role: str = "source_page_crop",
                    original_file_name: str = "", db_path: str | None = None) -> None:
    with _LOCK:
        conn = get_conn(db_path)
        try:
            conn.execute(
                """INSERT INTO question_import_draft_asset
                   (draft_id, role, file_path, original_file_name) VALUES (?,?,?,?)""",
                (draft_id, role, file_path, original_file_name),
            )
            conn.commit()
        finally:
            conn.close()


def list_drafts(review_status: list[str] | None = None,
                db_path: str | None = None) -> list[dict]:
    ensure_initialized(db_path)
    conn = get_conn(db_path)
    try:
        sql = "SELECT * FROM question_import_draft"
        params: list = []
        if review_status:
            sql += f" WHERE review_status IN ({','.join('?' * len(review_status))})"
            params.extend(review_status)
        sql += " ORDER BY updated_at DESC"
        items = []
        for row in conn.execute(sql, params).fetchall():
            item = dict(row)
            item["tags"] = json.loads(item["tags_json"]) if item.get("tags_json") else []
            item["choices"] = json.loads(item["choices_json"]) if item.get("choices_json") else []
            assets = conn.execute(
                "SELECT * FROM question_import_draft_asset WHERE draft_id=? ORDER BY sort_order",
                (item["draft_id"],),
            ).fetchall()
            item["assets"] = [dict(a) for a in assets]
            items.append(item)
        return items
    finally:
        conn.close()


def update_draft(draft_id: int, updates: dict, db_path: str | None = None) -> None:
    allowed = {"stem_tex", "answer_tex", "solution_tex", "difficulty", "note",
               "question_type", "review_status", "source_label", "proposed_action"}
    json_fields = {"choices": "choices_json", "tags": "tags_json"}
    sets, params = [], []
    for key, value in updates.items():
        if key in allowed:
            sets.append(f"{key}=?")
            params.append(value)
        elif key in json_fields:
            sets.append(f"{json_fields[key]}=?")
            params.append(_dump_json(value))
    if not sets:
        return
    sets.append("updated_at=?")
    params.extend([_now(), draft_id])
    with _LOCK:
        conn = get_conn(db_path)
        try:
            conn.execute(f"UPDATE question_import_draft SET {', '.join(sets)} WHERE draft_id=?", params)
            conn.commit()
        finally:
            conn.close()


def set_draft_status(draft_id: int, status: str, db_path: str | None = None) -> None:
    update_draft(draft_id, {"review_status": status}, db_path)


def commit_draft(draft_id: int, batch_id: int | None = None,
                 db_path: str | None = None) -> tuple[str | None, str]:
    """草稿确认入库：写正式题目 + 修订记录 + 导入报告，草稿标记 approved。
    返回 (question_id, 错误信息)。"""
    ensure_initialized(db_path)
    conn = get_conn(db_path)
    try:
        row = conn.execute("SELECT * FROM question_import_draft WHERE draft_id=?", (draft_id,)).fetchone()
        if not row:
            return None, "草稿不存在"
        draft = dict(row)
        if not (draft.get("stem_tex") or "").strip():
            set_draft_status(draft_id, "blocked", db_path)
            return None, "题干为空，无法入库"
    finally:
        conn.close()

    tags = json.loads(draft["tags_json"]) if draft.get("tags_json") else []
    choices = json.loads(draft["choices_json"]) if draft.get("choices_json") else []
    qtype_name = draft.get("question_type") or ""

    conn = get_conn(db_path)
    try:
        qtype_id = None
        if qtype_name:
            t = conn.execute("SELECT question_type_id FROM question_type WHERE name=?",
                             (qtype_name,)).fetchone()
            qtype_id = t["question_type_id"] if t else None
    finally:
        conn.close()

    # 组装标准 TeX（兼容旧 problem 环境导出）
    stem = draft["stem_tex"]
    canonical_parts = [stem]
    if choices:
        canonical_parts.append("\\begin{choices}")
        for c in choices:
            canonical_parts.append(f"\\choice{{{{{c}}}}}")
        canonical_parts.append("\\end{choices}")
    canonical_tex = "\n".join(canonical_parts)
    if draft.get("answer_tex"):
        canonical_tex += f"\n\\begin{{answer}}\n{draft['answer_tex']}\n\\end{{answer}}"
    if draft.get("solution_tex"):
        canonical_tex += f"\n\\begin{{solutions}}\n{draft['solution_tex']}\n\\end{{solutions}}"

    qid = insert_question({
        "question_type_id": qtype_id,
        "stem_tex": stem,
        "choices": choices,
        "answer_tex": draft.get("answer_tex", ""),
        "solution_tex": draft.get("solution_tex", ""),
        "difficulty": draft.get("difficulty"),
        "tags": tags,
        "note": draft.get("note", ""),
        "canonical_tex": canonical_tex,
        "raw_source_tex": draft.get("raw_source_text", ""),
        "normalized_status": "normalized",
    }, change_source="ocr", note=f"草稿 #{draft_id} 确认入库", db_path=db_path)

    set_draft_status(draft_id, "approved", db_path)
    if batch_id:
        add_report_item(batch_id, "inserted", source_file=draft.get("source_label", ""),
                        question_id=qid, db_path=db_path)
    return qid, ""


# ------------------------------------------------------------
# 首页统计
# ------------------------------------------------------------

def get_home_stats(db_path: str | None = None) -> dict:
    ensure_initialized(db_path)
    conn = get_conn(db_path)
    try:
        q_count = conn.execute("SELECT COUNT(*) c FROM question").fetchone()["c"]
        classic_count = conn.execute("SELECT COUNT(*) c FROM question WHERE is_classic=1").fetchone()["c"]
        draft_pending = conn.execute(
            "SELECT COUNT(*) c FROM question_import_draft WHERE review_status IN ('needs_review','ready')"
        ).fetchone()["c"]
        mistake_pending = conn.execute(
            "SELECT COUNT(*) c FROM mistake_record WHERE status='pending'"
        ).fetchone()["c"]
        return {
            "question_count": q_count,
            "classic_count": classic_count,
            "draft_pending": draft_pending,
            "mistake_pending": mistake_pending,
        }
    finally:
        conn.close()


# ------------------------------------------------------------
# 应用设置（知识点树等键值）
# ------------------------------------------------------------

def get_setting(key: str, default=None, db_path: str | None = None):
    ensure_initialized(db_path)
    conn = get_conn(db_path)
    try:
        row = conn.execute("SELECT value FROM app_setting WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return row["value"]
    finally:
        conn.close()


def set_setting(key: str, value, db_path: str | None = None) -> None:
    ensure_initialized(db_path)
    with _LOCK:
        conn = get_conn(db_path)
        try:
            conn.execute(
                """INSERT INTO app_setting (key, value, updated_at) VALUES (?,?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (key, _dump_json(value), _now()),
            )
            conn.commit()
        finally:
            conn.close()
