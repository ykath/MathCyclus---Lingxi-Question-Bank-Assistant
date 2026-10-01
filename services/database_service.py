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
    json_fields = {"choices": "choices_json", "tags": "tags_json", "extra": "extra_json"}
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


# ------------------------------------------------------------
# 题目资源（M2-T02：错题原始照片等）
# ------------------------------------------------------------

def add_question_asset(question_id: str, file_path: str, role: str = "source",
                       original_file_name: str = "", caption: str = "",
                       db_path: str | None = None) -> int:
    ensure_initialized(db_path)
    with _LOCK:
        conn = get_conn(db_path)
        try:
            cur = conn.execute(
                """INSERT INTO question_asset
                   (question_id, role, file_path, original_file_name, caption, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (question_id, role, file_path, original_file_name, caption, _now()),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def list_question_assets(question_id: str, role: str | None = None,
                         db_path: str | None = None) -> list[dict]:
    ensure_initialized(db_path)
    conn = get_conn(db_path)
    try:
        if role:
            rows = conn.execute(
                "SELECT * FROM question_asset WHERE question_id=? AND role=? ORDER BY sort_order",
                (question_id, role)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM question_asset WHERE question_id=? ORDER BY sort_order",
                (question_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ------------------------------------------------------------
# 错题本（M2-T01/T03）：错题生命周期与状态机
# ------------------------------------------------------------

WRONG_REASONS = ["计算失误", "概念不清", "审题错误", "方法不会", "其他"]
MISTAKE_STATUS = {"pending": "待重练", "mastered": "已掌握"}


def add_mistake(question_id: str, wrong_reason: str = "其他", wrong_date: str | None = None,
                source_text: str = "", original_photo_asset_id: int | None = None,
                pass_threshold: int = 2, db_path: str | None = None) -> tuple[int | None, str]:
    """把题目加入错题本。同一题只能有一条错题记录。"""
    ensure_initialized(db_path)
    if wrong_reason not in WRONG_REASONS:
        wrong_reason = "其他"
    with _LOCK:
        conn = get_conn(db_path)
        try:
            existing = conn.execute(
                "SELECT mistake_id, status FROM mistake_record WHERE question_id=?",
                (question_id,)).fetchone()
            if existing:
                return None, "这道题已经在错题本里了"
            cur = conn.execute(
                """INSERT INTO mistake_record
                   (question_id, wrong_reason, wrong_date, source_text,
                    original_photo_asset_id, status, pass_count, pass_threshold,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,'pending',0,?,?,?)""",
                (question_id, wrong_reason, wrong_date or _today(), source_text,
                 original_photo_asset_id, max(1, int(pass_threshold)), _now(), _now()),
            )
            conn.commit()
            return int(cur.lastrowid), ""
        finally:
            conn.close()


def get_mistake(question_id: str, db_path: str | None = None) -> dict | None:
    ensure_initialized(db_path)
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM mistake_record WHERE question_id=?", (question_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_mistake(question_id: str, updates: dict, db_path: str | None = None) -> bool:
    allowed = {"wrong_reason", "wrong_date", "source_text", "pass_threshold"}
    sets, params = [], []
    for key, value in updates.items():
        if key in allowed:
            sets.append(f"{key}=?")
            params.append(value)
    if not sets:
        return False
    sets.append("updated_at=?")
    params.extend([_now(), question_id])
    with _LOCK:
        conn = get_conn(db_path)
        try:
            cur = conn.execute(
                f"UPDATE mistake_record SET {', '.join(sets)} WHERE question_id=?", params)
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def list_mistakes(status: str | None = "pending", wrong_reason: str | None = None,
                  tags: list[str] | None = None, since_date: str | None = None,
                  idle_days: int | None = None,
                  db_path: str | None = None) -> list[dict]:
    """错题列表（联表题目）。idle_days：距上次练习超过 N 天（从未练过也算）。"""
    ensure_initialized(db_path)
    conn = get_conn(db_path)
    try:
        where, params = ["1=1"], []
        if status:
            where.append("m.status=?")
            params.append(status)
        if wrong_reason:
            where.append("m.wrong_reason=?")
            params.append(wrong_reason)
        if since_date:
            where.append("m.wrong_date>=?")
            params.append(since_date)
        if idle_days:
            where.append(
                "(m.last_practiced_at IS NULL OR date(m.last_practiced_at) <= date('now','localtime', ?))")
            params.append(f"-{int(idle_days)} days")
        rows = conn.execute(
            f"""SELECT m.*, q.stem_tex, q.choices_json, q.answer_tex, q.solution_tex,
                       q.difficulty, q.tags_json, q.note
                FROM mistake_record m JOIN question q ON q.question_id = m.question_id
                WHERE {' AND '.join(where)}
                ORDER BY m.updated_at DESC""", params).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["tags"] = json.loads(item["tags_json"]) if item.get("tags_json") else []
            item["choices"] = json.loads(item["choices_json"]) if item.get("choices_json") else []
            if tags and not all(t in item["tags"] for t in tags):
                continue
            items.append(item)
        return items
    finally:
        conn.close()


def record_practice(question_id: str, result: str, print_job_id: int | None = None,
                    note: str = "", db_path: str | None = None) -> tuple[bool, str]:
    """批改登记（M2-T03 状态机）：
    - correct：pass_count + 1，达到 pass_threshold 自动转「已掌握」
    - wrong：保持「待重练」，更新最近练习时间
    返回 (是否成功, 状态说明)。"""
    if result not in ("correct", "wrong"):
        return False, "结果只能是 correct 或 wrong"
    ensure_initialized(db_path)
    with _LOCK:
        conn = get_conn(db_path)
        try:
            mistake = conn.execute(
                "SELECT * FROM mistake_record WHERE question_id=? AND status='pending'",
                (question_id,)).fetchone()
            mistake_id = mistake["mistake_id"] if mistake else None
            conn.execute(
                """INSERT INTO practice_record
                   (question_id, mistake_id, print_job_id, practiced_at, result, note)
                   VALUES (?,?,?,?,?,?)""",
                (question_id, mistake_id, print_job_id, _now(), result, note),
            )
            if not mistake:
                conn.commit()
                return True, "已记录练习（该题不在待重练错题中）"

            if result == "correct":
                new_count = mistake["pass_count"] + 1
                if new_count >= mistake["pass_threshold"]:
                    conn.execute(
                        """UPDATE mistake_record SET pass_count=?, status='mastered',
                           last_practiced_at=?, updated_at=? WHERE mistake_id=?""",
                        (new_count, _now(), _now(), mistake_id))
                    msg = f"做对啦！已累计通过 {new_count} 次，移入「已掌握」🎉"
                else:
                    conn.execute(
                        """UPDATE mistake_record SET pass_count=?, last_practiced_at=?,
                           updated_at=? WHERE mistake_id=?""",
                        (new_count, _now(), _now(), mistake_id))
                    msg = f"已记录做对（{new_count}/{mistake['pass_threshold']} 次后移出错题本）"
            else:
                conn.execute(
                    "UPDATE mistake_record SET last_practiced_at=?, updated_at=? WHERE mistake_id=?",
                    (_now(), _now(), mistake_id))
                msg = "已记录做错，继续保持「待重练」"
            conn.commit()
            return True, msg
        finally:
            conn.close()


def restore_mistake(question_id: str, db_path: str | None = None) -> bool:
    """把「已掌握」错题恢复为「待重练」（清零通过次数）。"""
    ensure_initialized(db_path)
    with _LOCK:
        conn = get_conn(db_path)
        try:
            cur = conn.execute(
                """UPDATE mistake_record SET status='pending', pass_count=0, updated_at=?
                   WHERE question_id=? AND status='mastered'""",
                (_now(), question_id))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def remove_mistake(question_id: str, db_path: str | None = None) -> bool:
    """移出错题本（题目本身保留在题库）。"""
    ensure_initialized(db_path)
    with _LOCK:
        conn = get_conn(db_path)
        try:
            cur = conn.execute("DELETE FROM mistake_record WHERE question_id=?", (question_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def list_practice_records(question_id: str, db_path: str | None = None) -> list[dict]:
    """题目练习时间线（新→旧）。"""
    ensure_initialized(db_path)
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM practice_record WHERE question_id=? ORDER BY practiced_at DESC",
            (question_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mistake_reason_counts(db_path: str | None = None) -> dict[str, int]:
    """待重练错题的错因分布（M2-T04 计数条）。"""
    ensure_initialized(db_path)
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT wrong_reason, COUNT(*) c FROM mistake_record "
            "WHERE status='pending' GROUP BY wrong_reason").fetchall()
        return {r["wrong_reason"] or "其他": r["c"] for r in rows}
    finally:
        conn.close()


# ------------------------------------------------------------
# 找同类题（M2-T06）：按知识点重叠 + 难度接近推荐
# ------------------------------------------------------------

def find_similar_by_tags(question_id: str, limit: int = 5,
                         db_path: str | None = None) -> list[dict]:
    """按知识点标签重叠度推荐同类题，优先经典题；排除自身与已在错题本的题。"""
    ensure_initialized(db_path)
    source = get_question(question_id, db_path)
    if not source or not source.get("tags"):
        return []
    source_tags = set(source["tags"])
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            """SELECT question_id, stem_tex, difficulty, tags_json, is_classic, note
               FROM question
               WHERE question_id != ?
                 AND question_id NOT IN (SELECT question_id FROM mistake_record)""",
            (question_id,)).fetchall()
        scored = []
        for row in rows:
            item = dict(row)
            item_tags = set(json.loads(item["tags_json"]) if item.get("tags_json") else [])
            overlap = len(source_tags & item_tags)
            if overlap == 0:
                continue
            diff_gap = abs((item.get("difficulty") or 3) - (source.get("difficulty") or 3))
            scored.append((overlap, int(item.get("is_classic") or 0), -diff_gap, item))
        scored.sort(key=lambda x: (-x[0], -x[1], -x[2]))
        result = []
        for _ov, _classic, _gap, item in scored[:limit]:
            item["tags"] = json.loads(item["tags_json"]) if item.get("tags_json") else []
            result.append(item)
        return result
    finally:
        conn.close()


# ------------------------------------------------------------
# 打印篮底座（M2 先提供加入/查看能力，完整打印流程在 M3）
# ------------------------------------------------------------

def get_or_create_basket(db_path: str | None = None) -> int:
    """获取当前打印篮（status='draft' 的 print_job），没有则创建。"""
    ensure_initialized(db_path)
    with _LOCK:
        conn = get_conn(db_path)
        try:
            row = conn.execute(
                "SELECT print_job_id FROM print_job WHERE status='draft' "
                "ORDER BY updated_at DESC LIMIT 1").fetchone()
            if row:
                return row["print_job_id"]
            cur = conn.execute(
                "INSERT INTO print_job (title, status) VALUES ('打印篮', 'draft')")
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def basket_add(question_id: str, db_path: str | None = None) -> tuple[bool, str]:
    basket_id = get_or_create_basket(db_path)
    with _LOCK:
        conn = get_conn(db_path)
        try:
            exists = conn.execute(
                "SELECT 1 FROM print_job_item WHERE print_job_id=? AND question_id=?",
                (basket_id, question_id)).fetchone()
            if exists:
                return False, "这道题已在打印篮里"
            order = conn.execute(
                "SELECT COALESCE(MAX(display_order),0)+1 n FROM print_job_item WHERE print_job_id=?",
                (basket_id,)).fetchone()["n"]
            conn.execute(
                "INSERT INTO print_job_item (print_job_id, question_id, display_order) VALUES (?,?,?)",
                (basket_id, question_id, order))
            conn.execute("UPDATE print_job SET updated_at=? WHERE print_job_id=?",
                         (_now(), basket_id))
            conn.commit()
            return True, "已加入打印篮"
        finally:
            conn.close()


def basket_remove(question_id: str, db_path: str | None = None) -> bool:
    basket_id = get_or_create_basket(db_path)
    with _LOCK:
        conn = get_conn(db_path)
        try:
            cur = conn.execute(
                "DELETE FROM print_job_item WHERE print_job_id=? AND question_id=?",
                (basket_id, question_id))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def basket_list(db_path: str | None = None) -> list[dict]:
    basket_id = get_or_create_basket(db_path)
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            """SELECT q.question_id, q.stem_tex, q.tags_json, q.difficulty, p.display_order
               FROM print_job_item p JOIN question q ON q.question_id = p.question_id
               WHERE p.print_job_id=? ORDER BY p.display_order""", (basket_id,)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["tags"] = json.loads(item["tags_json"]) if item.get("tags_json") else []
            items.append(item)
        return items
    finally:
        conn.close()


def basket_clear(db_path: str | None = None) -> None:
    basket_id = get_or_create_basket(db_path)
    with _LOCK:
        conn = get_conn(db_path)
        try:
            conn.execute("DELETE FROM print_job_item WHERE print_job_id=?", (basket_id,))
            conn.commit()
        finally:
            conn.close()


# ------------------------------------------------------------
# 打印任务（M3-T06/T07）
# ------------------------------------------------------------

def finalize_print_job(basket_id: int, title: str, settings: dict,
                       pdf_path: str = "", db_path: str | None = None) -> None:
    """打印篮生成产物后：更新标题/设置/PDF 路径，状态转 generated。"""
    with _LOCK:
        conn = get_conn(db_path)
        try:
            conn.execute(
                """UPDATE print_job SET title=?, settings_json=?, pdf_path=?, status='generated',
                   updated_at=? WHERE print_job_id=?""",
                (title, _dump_json(settings), pdf_path, _now(), basket_id),
            )
            conn.commit()
        finally:
            conn.close()


def list_print_jobs(status: list[str] | None = None, limit: int = 20,
                    db_path: str | None = None) -> list[dict]:
    """打印历史（新→旧），不含当前打印篮草稿。"""
    ensure_initialized(db_path)
    conn = get_conn(db_path)
    try:
        where = "p.status != 'draft'"
        params: list = []
        if status:
            where += f" AND p.status IN ({','.join('?' * len(status))})"
            params.extend(status)
        rows = conn.execute(
            f"""SELECT p.*, (SELECT COUNT(*) FROM print_job_item i
                             WHERE i.print_job_id=p.print_job_id) AS item_count,
                       (SELECT COUNT(*) FROM practice_record r
                             WHERE r.print_job_id=p.print_job_id) AS graded_count
                FROM print_job p WHERE {where}
                ORDER BY p.updated_at DESC LIMIT ?""",
            (*params, limit)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            try:
                item["settings"] = json.loads(item["settings_json"]) if item.get("settings_json") else {}
            except json.JSONDecodeError:
                item["settings"] = {}
            items.append(item)
        return items
    finally:
        conn.close()


def get_print_job_items(print_job_id: int, db_path: str | None = None) -> list[dict]:
    ensure_initialized(db_path)
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            """SELECT q.question_id, q.stem_tex, q.tags_json, q.difficulty,
                      q.answer_tex, q.solution_tex, p.display_order
               FROM print_job_item p JOIN question q ON q.question_id = p.question_id
               WHERE p.print_job_id=? ORDER BY p.display_order""",
            (print_job_id,)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["tags"] = json.loads(item["tags_json"]) if item.get("tags_json") else []
            # 是否已批改
            graded = conn.execute(
                "SELECT result FROM practice_record WHERE print_job_id=? AND question_id=?",
                (print_job_id, item["question_id"])).fetchone()
            item["graded_result"] = graded["result"] if graded else None
            item["in_mistakes"] = conn.execute(
                "SELECT 1 FROM mistake_record WHERE question_id=? AND status='pending'",
                (item["question_id"],)).fetchone() is not None
            items.append(item)
        return items
    finally:
        conn.close()


def mark_print_job_status(print_job_id: int, status: str, db_path: str | None = None) -> None:
    with _LOCK:
        conn = get_conn(db_path)
        try:
            conn.execute("UPDATE print_job SET status=?, updated_at=? WHERE print_job_id=?",
                         (status, _now(), print_job_id))
            conn.commit()
        finally:
            conn.close()


def close_basket(basket_id: int, db_path: str | None = None) -> None:
    """打印完成后打印篮不再显示为草稿（历史保留，可重印/批改）。"""
    mark_print_job_status(basket_id, "printed", db_path)


def basket_move(question_id: str, direction: int, db_path: str | None = None) -> None:
    """打印篮内题目上移/下移（direction=-1 上移，+1 下移）。"""
    basket_id = get_or_create_basket(db_path)
    with _LOCK:
        conn = get_conn(db_path)
        try:
            rows = conn.execute(
                "SELECT question_id, display_order FROM print_job_item "
                "WHERE print_job_id=? ORDER BY display_order", (basket_id,)).fetchall()
            ids = [r["question_id"] for r in rows]
            if question_id not in ids:
                return
            idx = ids.index(question_id)
            swap = idx + direction
            if swap < 0 or swap >= len(ids):
                return
            ids[idx], ids[swap] = ids[swap], ids[idx]
            for order, qid in enumerate(ids, 1):
                conn.execute(
                    "UPDATE print_job_item SET display_order=? WHERE print_job_id=? AND question_id=?",
                    (order, basket_id, qid))
            conn.commit()
        finally:
            conn.close()


# ------------------------------------------------------------
# 复习建议（M4-T01）：到期错题推荐
# ------------------------------------------------------------

def suggest_review_mistakes(days: int = 3, limit: int = 10,
                            db_path: str | None = None) -> list[dict]:
    """建议今天重练的错题：待重练 且（从未练过 或 距上次练习 ≥ days 天）。
    按最久未练优先。"""
    ensure_initialized(db_path)
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            """SELECT m.*, q.stem_tex, q.tags_json, q.difficulty
               FROM mistake_record m JOIN question q ON q.question_id = m.question_id
               WHERE m.status='pending'
                 AND (m.last_practiced_at IS NULL
                      OR date(m.last_practiced_at) <= date('now','localtime', ?))
               ORDER BY m.last_practiced_at IS NOT NULL,
                        m.last_practiced_at ASC, m.wrong_date ASC
               LIMIT ?""",
            (f"-{int(days)} days", limit)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["tags"] = json.loads(item["tags_json"]) if item.get("tags_json") else []
            items.append(item)
        return items
    finally:
        conn.close()
