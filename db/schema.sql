-- LMS AI Copilot — SQLite Schema
-- (pgvector 없이 embedding은 TEXT로 저장, 나중에 PostgreSQL 전환 가능)

CREATE TABLE IF NOT EXISTS User (
    user_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    lms_id            TEXT    NOT NULL UNIQUE,
    enc_session_cookie TEXT,
    scraping_interval INTEGER DEFAULT 3600,
    last_sync_at      TEXT
);

CREATE TABLE IF NOT EXISTS Course (
    course_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    lms_url_id  TEXT UNIQUE,
    course_code TEXT,
    title       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS Enrollment (
    enroll_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL REFERENCES User(user_id),
    course_id INTEGER NOT NULL REFERENCES Course(course_id),
    role      TEXT NOT NULL DEFAULT 'student',
    UNIQUE (user_id, course_id)
);

CREATE TABLE IF NOT EXISTS Material (
    material_id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id   INTEGER NOT NULL REFERENCES Course(course_id),
    title       TEXT,
    file_type   TEXT,
    file_path   TEXT,
    checksum    TEXT,
    synced_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS Doc_Chunk (
    chunk_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER NOT NULL REFERENCES Material(material_id),
    content     TEXT NOT NULL,
    page_ref    INTEGER,
    chunk_index INTEGER,
    embedding   TEXT  -- JSON array, Phase 2에서 pgvector로 전환
);

CREATE TABLE IF NOT EXISTS Learning_Activity (
    activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES User(user_id),
    course_id   INTEGER NOT NULL REFERENCES Course(course_id),
    title       TEXT,
    status      TEXT,
    due_date    TEXT,
    description TEXT
);

CREATE TABLE IF NOT EXISTS Personal_Log (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES User(user_id),
    course_id   INTEGER NOT NULL REFERENCES Course(course_id),
    material_id INTEGER REFERENCES Material(material_id),
    stay_time   INTEGER
);

-- FTS5 전문 검색 인덱스 (Doc_Chunk.content 기반)
CREATE VIRTUAL TABLE IF NOT EXISTS Doc_Chunk_fts USING fts5(
    content,
    content='Doc_Chunk',
    content_rowid='chunk_id',
    tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS Chat_Session (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES User(user_id),
    course_id  INTEGER REFERENCES Course(course_id),
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS Chat_Log (
    chat_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     INTEGER NOT NULL REFERENCES Chat_Session(session_id),
    role           TEXT NOT NULL,
    content        TEXT NOT NULL,
    keywords       TEXT,  -- 검색용 키워드 (공백 구분)
    sources        TEXT,  -- JSON [{chunk_id, material_id, page_ref}]
    feedback_score INTEGER,
    created_at     TEXT DEFAULT (datetime('now'))
);

-- Chat_Log 전문 검색 인덱스
CREATE VIRTUAL TABLE IF NOT EXISTS Chat_Log_fts USING fts5(
    content,
    keywords,
    content='Chat_Log',
    content_rowid='chat_id',
    tokenize='unicode61'
);
