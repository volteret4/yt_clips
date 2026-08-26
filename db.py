import os
import sqlite3

DB_PATH = os.environ.get("DB_PATH", "/app/clips.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id            INTEGER PRIMARY KEY,
    video_id      TEXT UNIQUE NOT NULL,
    url           TEXT NOT NULL,
    title         TEXT,
    duration      REAL,
    file_path     TEXT,
    downloaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clips (
    id            INTEGER PRIMARY KEY,
    source_id     INTEGER NOT NULL REFERENCES sources(id),
    label         TEXT,
    start_seconds REAL NOT NULL,
    end_seconds   REAL NOT NULL,
    file_path     TEXT NOT NULL,
    duration      REAL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS montages (
    id               INTEGER PRIMARY KEY,
    title            TEXT,
    clip_ids_json    TEXT NOT NULL,
    file_path        TEXT,
    youtube_video_id TEXT,
    status           TEXT NOT NULL DEFAULT 'draft',
    error            TEXT,
    created_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS youtube_auth (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    token         TEXT,
    refresh_token TEXT,
    token_uri     TEXT,
    client_id     TEXT,
    client_secret TEXT,
    scopes        TEXT,
    expiry        TEXT
);
CREATE INDEX IF NOT EXISTS idx_clips_source ON clips(source_id);
"""


def init_db(path: str = DB_PATH) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def get_conn() -> sqlite3.Connection:
    # DB_PATH explícito (no el default de init_db, fijado en tiempo de
    # definición) -- ver services/discos_pendientes/db.py, mismo motivo:
    # un cambio de DB_PATH en caliente (tests) debe respetarse también aquí.
    init_db(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
