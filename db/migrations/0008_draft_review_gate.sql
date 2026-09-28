ALTER TABLE question_import_draft ADD COLUMN content_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE question_import_draft ADD COLUMN approved_content_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE question_import_draft ADD COLUMN approved_by TEXT NOT NULL DEFAULT '';
ALTER TABLE question_import_draft ADD COLUMN approved_at TEXT;

CREATE TABLE IF NOT EXISTS draft_review_event (
    event_id TEXT PRIMARY KEY,
    draft_id TEXT NOT NULL REFERENCES question_import_draft(draft_id) ON DELETE CASCADE,
    batch_id TEXT NOT NULL REFERENCES import_batch(batch_id) ON DELETE CASCADE,
    stage TEXT NOT NULL DEFAULT 'human_review',
    from_status TEXT NOT NULL DEFAULT '',
    to_status TEXT NOT NULL DEFAULT '',
    decision TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    operator TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_draft_review_event_draft
    ON draft_review_event(draft_id, created_at);
CREATE INDEX IF NOT EXISTS idx_draft_review_event_batch
    ON draft_review_event(batch_id, created_at);

INSERT INTO app_meta(key, value, updated_at)
VALUES ('schema_version', '8', CURRENT_TIMESTAMP)
ON CONFLICT(key) DO UPDATE SET
    value = excluded.value,
    updated_at = excluded.updated_at;
