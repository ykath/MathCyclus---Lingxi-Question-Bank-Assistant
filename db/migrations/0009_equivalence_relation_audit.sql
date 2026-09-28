ALTER TABLE question_equivalence ADD COLUMN relation_source TEXT NOT NULL DEFAULT 'manual';
ALTER TABLE question_equivalence ADD COLUMN updated_at TEXT NOT NULL DEFAULT '';
UPDATE question_equivalence SET updated_at = COALESCE(NULLIF(created_at, ''), CURRENT_TIMESTAMP)
WHERE updated_at = '';

CREATE TABLE IF NOT EXISTS question_equivalence_event (
    event_id TEXT PRIMARY KEY,
    equivalence_id TEXT NOT NULL,
    action TEXT NOT NULL,
    before_status TEXT NOT NULL DEFAULT '',
    after_status TEXT NOT NULL DEFAULT '',
    before_relation_type TEXT NOT NULL DEFAULT '',
    after_relation_type TEXT NOT NULL DEFAULT '',
    relation_source TEXT NOT NULL DEFAULT '',
    operator TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_question_equivalence_event_relation
    ON question_equivalence_event(equivalence_id, created_at);
CREATE INDEX IF NOT EXISTS idx_question_equivalence_source
    ON question_equivalence(relation_source, review_status);

INSERT INTO app_meta(key, value, updated_at)
VALUES ('schema_version', '9', CURRENT_TIMESTAMP)
ON CONFLICT(key) DO UPDATE SET
    value = excluded.value,
    updated_at = excluded.updated_at;
