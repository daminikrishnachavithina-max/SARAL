"""SARAL database: tables for sources, opportunities, rules, and history."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "saral.db"

SCHEMA = """
 CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    organization TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL,
    authority_rank INTEGER DEFAULT 1,
    poll_minutes INTEGER DEFAULT 360,
    active INTEGER DEFAULT 0,
    robots_allowed INTEGER,
    content_hash TEXT,
    last_checked_at TEXT,
    last_success_at TEXT,
    last_status TEXT,
    last_error TEXT,
    consecutive_failures INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    org_name TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT DEFAULT 'education',
    state TEXT,
    description TEXT,
    official_url TEXT NOT NULL,
    apply_url TEXT,
    deadline TEXT,
    application_status TEXT DEFAULT 'unknown',
    funding TEXT,
    documents_json TEXT,
    published_at TEXT,
    verification_status TEXT DEFAULT 'unverified',
    last_checked_at TEXT,
    last_success_at TEXT,
    current_version INTEGER DEFAULT 1,
    UNIQUE(source_id, name)
);
CREATE TABLE IF NOT EXISTS criteria (
    id INTEGER PRIMARY KEY,
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
    field TEXT NOT NULL,
    operator TEXT NOT NULL,
    value TEXT NOT NULL,
    label TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS opportunity_versions (
    id INTEGER PRIMARY KEY,
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
    version INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    change_summary TEXT,
    source_url TEXT,
    retrieved_at TEXT NOT NULL,
    verified_at TEXT
);
CREATE TABLE IF NOT EXISTS pending_changes (
    id INTEGER PRIMARY KEY,
    opportunity_id INTEGER REFERENCES opportunities(id),
    source_id INTEGER REFERENCES sources(id),
    proposed_json TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fetch_log (
    id INTEGER PRIMARY KEY,
    source_id INTEGER REFERENCES sources(id),
    checked_at TEXT NOT NULL,
    outcome TEXT NOT NULL,
    http_status INTEGER,
    message TEXT
);
"""


def get_connection():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_connection() as conn:
        conn.executescript(SCHEMA)


if __name__ == "__main__":
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    print("Database created at:", DB_PATH)
    print("Tables:", ", ".join(r["name"] for r in rows))
