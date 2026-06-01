import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "law_qa.db"

_DDL = """
CREATE TABLE IF NOT EXISTS laws (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    article_no  TEXT,
    content     TEXT NOT NULL,
    law_type    TEXT,
    source      TEXT,
    fetched_at  TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS laws_fts USING fts5(
    title, article_no, content,
    content='laws',
    content_rowid='id'
);

CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS query_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL,
    question        TEXT NOT NULL,
    answer          TEXT NOT NULL,
    source_law_ids  TEXT,
    has_image       INTEGER DEFAULT 0,
    confidence      INTEGER,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS query_history_fts USING fts5(
    question, answer,
    content='query_history',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS laws_ai AFTER INSERT ON laws BEGIN
    INSERT INTO laws_fts(rowid, title, article_no, content)
    VALUES (new.id, new.title, new.article_no, new.content);
END;

CREATE TRIGGER IF NOT EXISTS laws_ad AFTER DELETE ON laws BEGIN
    INSERT INTO laws_fts(laws_fts, rowid, title, article_no, content)
    VALUES ('delete', old.id, old.title, old.article_no, old.content);
END;

CREATE TRIGGER IF NOT EXISTS laws_au AFTER UPDATE ON laws BEGIN
    INSERT INTO laws_fts(laws_fts, rowid, title, article_no, content)
    VALUES ('delete', old.id, old.title, old.article_no, old.content);
    INSERT INTO laws_fts(rowid, title, article_no, content)
    VALUES (new.id, new.title, new.article_no, new.content);
END;

CREATE TRIGGER IF NOT EXISTS qh_ai AFTER INSERT ON query_history BEGIN
    INSERT INTO query_history_fts(rowid, question, answer)
    VALUES (new.id, new.question, new.answer);
END;

CREATE TRIGGER IF NOT EXISTS qh_ad AFTER DELETE ON query_history BEGIN
    INSERT INTO query_history_fts(query_history_fts, rowid, question, answer)
    VALUES ('delete', old.id, old.question, old.answer);
END;

CREATE TRIGGER IF NOT EXISTS qh_au AFTER UPDATE ON query_history BEGIN
    INSERT INTO query_history_fts(query_history_fts, rowid, question, answer)
    VALUES ('delete', old.id, old.question, old.answer);
    INSERT INTO query_history_fts(rowid, question, answer)
    VALUES (new.id, new.question, new.answer);
END;
"""


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
