-- ============================================================
-- MathEx 家长版 · SQLite 主数据库 Schema
-- 版本：v1（M0-T04）
-- 依据：docs/planning/题库数据库重构实施规划.md + PRD.md 第 5 节
--
-- 设计原则：
--   1. question_id 是题目唯一稳定身份，所有关系都挂到它；
--   2. 关系属性（试卷题号、教材页码、专题排序）放关系表，不污染题目本体；
--   3. AI/OCR 内容一律先进草稿表，人工确认后才写正式表；
--   4. 每次正式写入都留修订记录，可审计、可回滚；
--   5. JSON 字段（*_json）存放数组/对象，便于向后兼容扩展。
-- ============================================================

PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------
-- 题型表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS question_type (
    question_type_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL UNIQUE,          -- 单选题 / 填空题 / 解答题
    code              TEXT,                          -- single_choice / fill_blank / solution
    description       TEXT
);

-- ------------------------------------------------------------
-- 题目本体表：只保存题目本身
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS question (
    question_id         TEXT PRIMARY KEY,            -- 稳定 ID，如 Q000001
    question_type_id    INTEGER REFERENCES question_type(question_type_id),
    stem_tex            TEXT NOT NULL,               -- 题干 TeX
    choices_json        TEXT,                        -- 选项数组 ["...","..."] 或 {"A":"..."}
    answer_tex          TEXT,                        -- 答案 TeX
    solution_tex        TEXT,                        -- 解析 TeX
    difficulty          INTEGER CHECK (difficulty BETWEEN 1 AND 5),
    tags_json           TEXT,                        -- 知识点标签数组 ["函数","导数"]
    note                TEXT,                        -- 家长备注
    is_classic          INTEGER NOT NULL DEFAULT 0,  -- 经典题标记（家长版新增）
    official_flag       INTEGER NOT NULL DEFAULT 0,  -- 是否官方题源
    canonical_tex       TEXT,                        -- 标准化完整 TeX（缓存，导出用）
    raw_source_tex      TEXT,                        -- 原始导入文本
    normalized_status   TEXT NOT NULL DEFAULT 'draft'
                        CHECK (normalized_status IN ('raw','draft','normalized','needs_review')),
    created_at          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    last_manual_edit_at TEXT
);

-- ------------------------------------------------------------
-- 教研分析表（数据保留，家长版界面默认不出现）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS question_analysis (
    question_id       TEXT PRIMARY KEY REFERENCES question(question_id) ON DELETE CASCADE,
    target_tex        TEXT,                          -- 考查目的
    production_tex    TEXT,                          -- 命题过程
    evaluation_tex    TEXT,                          -- 试题评析
    marking_data_tex  TEXT,                          -- 阅卷数据
    warning_tex       TEXT,                          -- 易错警示
    reference_text    TEXT,                          -- 参考文献
    extra_json        TEXT
);

-- ------------------------------------------------------------
-- 题目资源表：题图、答案图、原始扫描件等
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS question_asset (
    asset_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id        TEXT NOT NULL REFERENCES question(question_id) ON DELETE CASCADE,
    role               TEXT NOT NULL                 -- problem/answer/solution/source/thumbnail
                       CHECK (role IN ('problem','answer','solution','source','thumbnail')),
    file_path          TEXT NOT NULL,                -- 本地相对路径，如 assets/questions/Q000001/problem-1.png
    original_file_name TEXT,
    mime_type          TEXT,
    width              INTEGER,
    height             INTEGER,
    file_hash          TEXT,
    caption            TEXT,                         -- 图片别名，TeX 中 \questionasset{caption} 引用
    sort_order         INTEGER NOT NULL DEFAULT 0,
    created_at         TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_question_asset_qid ON question_asset(question_id);

-- ------------------------------------------------------------
-- 修订记录表：人工/AI/OCR/批量/迁移 全量留痕
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS question_revision (
    revision_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id         TEXT NOT NULL REFERENCES question(question_id) ON DELETE CASCADE,
    change_source       TEXT NOT NULL                -- manual/ai/ocr/batch_import/batch_normalize/migration
                        CHECK (change_source IN ('manual','ai','ocr','batch_import','batch_normalize','migration')),
    changed_fields_json TEXT,
    before_json         TEXT,
    after_json          TEXT,
    operator            TEXT,
    note                TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_question_revision_qid ON question_revision(question_id);

-- ------------------------------------------------------------
-- 试卷与试卷题目关系
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS paper (
    paper_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    year          INTEGER,
    paper_series  TEXT,                              -- 全国卷/新高考卷/地方卷
    track         TEXT,                              -- 文科/理科/新高考/综合
    paper_name    TEXT NOT NULL,                     -- 标准试卷名称
    source_name   TEXT,                              -- 原始录入中的试卷名
    description   TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS paper_question (
    paper_question_id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id          INTEGER NOT NULL REFERENCES paper(paper_id) ON DELETE CASCADE,
    question_id       TEXT NOT NULL REFERENCES question(question_id) ON DELETE CASCADE,
    question_number   TEXT,                          -- 题号是关系属性，不是题目本体属性
    sub_number        TEXT,
    display_order     INTEGER NOT NULL DEFAULT 0,
    origin_tex        TEXT,
    location_tex      TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE (paper_id, question_id, question_number, sub_number)
);
CREATE INDEX IF NOT EXISTS idx_paper_question_qid ON paper_question(question_id);

-- ------------------------------------------------------------
-- 教材库：书籍 → 章节 → 习题关系
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS book (
    book_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title              TEXT NOT NULL,
    publisher          TEXT,
    edition            TEXT,
    grade              TEXT,
    volume             TEXT,                         -- 必修/选择性必修/上册/下册
    curriculum_version TEXT,
    description        TEXT
);

CREATE TABLE IF NOT EXISTS book_section (
    section_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id           INTEGER NOT NULL REFERENCES book(book_id) ON DELETE CASCADE,
    parent_section_id INTEGER REFERENCES book_section(section_id),
    title             TEXT NOT NULL,
    section_level     INTEGER NOT NULL DEFAULT 1,
    page_start        INTEGER,
    page_end          INTEGER,
    sort_order        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_book_section_book ON book_section(book_id);

CREATE TABLE IF NOT EXISTS book_exercise_question (
    book_exercise_question_id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id           INTEGER NOT NULL REFERENCES book(book_id) ON DELETE CASCADE,
    section_id        INTEGER REFERENCES book_section(section_id),
    question_id       TEXT NOT NULL REFERENCES question(question_id) ON DELETE CASCADE,
    page_number       INTEGER,
    column_name       TEXT,                          -- 栏目：例题/练习/习题/思考/探究…
    exercise_number   TEXT,
    sub_number        TEXT,
    display_order     INTEGER NOT NULL DEFAULT 0,
    source_note       TEXT
);
CREATE INDEX IF NOT EXISTS idx_book_exercise_qid ON book_exercise_question(question_id);

-- ------------------------------------------------------------
-- 专题系统：大专题 → 小专题 → 题目（也用于知识点树与经典题集）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS topic_module (
    module_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS topic (
    topic_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id   INTEGER REFERENCES topic_module(module_id),
    name        TEXT NOT NULL,
    file_name   TEXT,
    description TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE (module_id, name)
);

CREATE TABLE IF NOT EXISTS topic_question (
    topic_question_id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id      INTEGER NOT NULL REFERENCES topic(topic_id) ON DELETE CASCADE,
    question_id   TEXT NOT NULL REFERENCES question(question_id) ON DELETE CASCADE,
    group_name    TEXT,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    topic_note    TEXT,
    UNIQUE (topic_id, question_id)
);
CREATE INDEX IF NOT EXISTS idx_topic_question_qid ON topic_question(question_id);

-- ------------------------------------------------------------
-- 导入批次与报告
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS import_batch (
    batch_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    import_type TEXT NOT NULL                        -- tex/pdf/image/ocr/ai/manual
                CHECK (import_type IN ('tex','pdf','image','ocr','ai','manual')),
    source_path TEXT,
    mode        TEXT NOT NULL DEFAULT 'dry_run' CHECK (mode IN ('dry_run','commit')),
    started_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    finished_at TEXT,
    summary     TEXT,
    extra_json  TEXT
);

CREATE TABLE IF NOT EXISTS import_report_item (
    item_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id     INTEGER NOT NULL REFERENCES import_batch(batch_id) ON DELETE CASCADE,
    source_file  TEXT,
    question_id  TEXT REFERENCES question(question_id),
    status       TEXT NOT NULL                       -- inserted/updated/skipped/error/needs_review
                 CHECK (status IN ('inserted','updated','skipped','error','needs_review')),
    reason       TEXT,
    detail       TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_import_report_batch ON import_report_item(batch_id);

-- ------------------------------------------------------------
-- AI/OCR/PDF 草稿：未确认前绝不污染正式题库
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS question_import_draft (
    draft_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id          INTEGER REFERENCES import_batch(batch_id),
    source_item_id    TEXT,                          -- 原始材料中的题目标识，如 page_12_q_03
    source_label      TEXT,                          -- 显示名，如「2025 全国II卷 第3题」
    proposed_action   TEXT NOT NULL DEFAULT 'insert'
                      CHECK (proposed_action IN ('insert','update','skip')),
    target_question_id TEXT REFERENCES question(question_id),
    review_status     TEXT NOT NULL DEFAULT 'needs_review'
                      CHECK (review_status IN ('needs_review','ready','blocked','approved','rejected')),
    question_type     TEXT,
    stem_tex          TEXT,
    choices_json      TEXT,
    answer_tex        TEXT,
    solution_tex      TEXT,
    difficulty        INTEGER CHECK (difficulty BETWEEN 1 AND 5),
    tags_json         TEXT,
    note              TEXT,
    official_flag     INTEGER NOT NULL DEFAULT 0,
    raw_source_text   TEXT,
    confidence_json   TEXT,                          -- 分字段置信度
    validation_json   TEXT,                          -- 校验结果与 warning
    extra_json        TEXT,                          -- 页码、题号、坐标等
    created_at        TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_draft_status ON question_import_draft(review_status);

CREATE TABLE IF NOT EXISTS question_import_draft_asset (
    draft_asset_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id           INTEGER NOT NULL REFERENCES question_import_draft(draft_id) ON DELETE CASCADE,
    role               TEXT                          -- problem_image/solution_image/source_page_crop/unknown
                       CHECK (role IN ('problem_image','solution_image','source_page_crop','unknown')),
    file_path          TEXT NOT NULL,
    original_file_name TEXT,
    caption            TEXT,
    sort_order         INTEGER NOT NULL DEFAULT 0,
    extra_json         TEXT
);
CREATE INDEX IF NOT EXISTS idx_draft_asset_draft ON question_import_draft_asset(draft_id);

-- ============================================================
-- 家长版新增：错题 / 练习反馈 / 打印
-- ============================================================

-- ------------------------------------------------------------
-- 错题记录：错题的独立生命周期
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mistake_record (
    mistake_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id             TEXT NOT NULL UNIQUE REFERENCES question(question_id) ON DELETE CASCADE,
    wrong_reason            TEXT                     -- 计算失误/概念不清/审题错误/方法不会/其他
                            CHECK (wrong_reason IN ('计算失误','概念不清','审题错误','方法不会','其他')),
    wrong_date              TEXT NOT NULL,           -- 出错日期 YYYY-MM-DD
    source_text             TEXT,                    -- 出处自由文本，如「2026 秋 期中卷」
    original_photo_asset_id INTEGER REFERENCES question_asset(asset_id),  -- 孩子笔迹原图
    status                  TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','mastered')),     -- 待重练/已掌握
    pass_count              INTEGER NOT NULL DEFAULT 0,                   -- 累计做对次数
    pass_threshold          INTEGER NOT NULL DEFAULT 2,                   -- 达到即转已掌握（可设置）
    last_practiced_at       TEXT,
    created_at              TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_mistake_status ON mistake_record(status);

-- ------------------------------------------------------------
-- 练习反馈记录：每次批改逐题留痕
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS practice_record (
    practice_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id   TEXT NOT NULL REFERENCES question(question_id) ON DELETE CASCADE,
    mistake_id    INTEGER REFERENCES mistake_record(mistake_id),
    print_job_id  INTEGER,                           -- 关联打印任务（逻辑外键，见 print_job）
    practiced_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    result        TEXT NOT NULL CHECK (result IN ('correct','wrong')),
    note          TEXT
);
CREATE INDEX IF NOT EXISTS idx_practice_qid ON practice_record(question_id);
CREATE INDEX IF NOT EXISTS idx_practice_time ON practice_record(practiced_at);

-- ------------------------------------------------------------
-- 打印任务与打印篮条目
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS print_job (
    print_job_id INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL DEFAULT '数学练习',
    settings_json TEXT,                              -- 纸张/留白/题答分离/字号等
    pdf_path     TEXT,                               -- 生成的 PDF 相对路径
    status       TEXT NOT NULL DEFAULT 'draft'       -- draft(组题中)/generated/printed/graded
                 CHECK (status IN ('draft','generated','printed','graded')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS print_job_item (
    print_job_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    print_job_id  INTEGER NOT NULL REFERENCES print_job(print_job_id) ON DELETE CASCADE,
    question_id   TEXT NOT NULL REFERENCES question(question_id) ON DELETE CASCADE,
    display_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE (print_job_id, question_id)
);
CREATE INDEX IF NOT EXISTS idx_print_item_job ON print_job_item(print_job_id);

-- ------------------------------------------------------------
-- 应用设置（首启向导、AI 配置之外的键值）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_setting (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ------------------------------------------------------------
-- 内置题型种子数据
-- ------------------------------------------------------------
INSERT OR IGNORE INTO question_type (name, code, description) VALUES
    ('单选题', 'single_choice', '四选一选择题'),
    ('多选题', 'multi_choice',  '多项选择题'),
    ('填空题', 'fill_blank',    '填空题'),
    ('解答题', 'solution',      '需要书写过程的解答题');
