"""SQLite persistence for sessions and messages."""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Where the SQLite file lives. Defaults to the project directory for local use.
# On a hosting platform with an ephemeral filesystem (Render, Railway, Fly, ...)
# point this at a persistent disk, e.g. THERAPYBOT_DB_PATH=/var/data/sessions.db,
# otherwise every deploy or restart wipes all transcripts.
DB_PATH = Path(os.environ.get("THERAPYBOT_DB_PATH") or Path(__file__).parent / "sessions.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    student_name TEXT NOT NULL,
    language TEXT NOT NULL,
    disorder_id TEXT NOT NULL,
    persona_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    diagnosis_guess TEXT,
    diagnosis_correct INTEGER,
    justification TEXT,
    diagnosed_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    # timeout: wait for a concurrent writer instead of raising "database is
    # locked" when several gunicorn threads store messages at the same time.
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        # WAL lets readers (admin page, exports) run while a write is in flight.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)


def create_session(student_name, language, disorder_id, persona):
    session_id = uuid.uuid4().hex
    with connect() as conn:
        conn.execute(
            "INSERT INTO sessions (id, student_name, language, disorder_id, persona_json, started_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, student_name, language, disorder_id, json.dumps(persona), _now()),
        )
    return session_id


def get_session(session_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        return None
    session = dict(row)
    session["persona"] = json.loads(session.pop("persona_json"))
    return session


def add_message(session_id, role, content):
    with connect() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, _now()),
        )


def get_messages(session_id):
    with connect() as conn:
        rows = conn.execute(
            "SELECT role, content, created_at FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def count_user_messages(session_id):
    """Number of student turns so far — used to enforce the per-session cap."""
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ? AND role = 'user'",
            (session_id,),
        ).fetchone()
    return row[0]


def record_diagnosis(session_id, guess, correct, justification):
    with connect() as conn:
        conn.execute(
            "UPDATE sessions SET diagnosis_guess = ?, diagnosis_correct = ?,"
            " justification = ?, diagnosed_at = ? WHERE id = ?",
            (guess, int(correct), justification, _now(), session_id),
        )


def list_sessions():
    """All sessions, newest first, with message counts — for the admin page."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT s.*, COUNT(m.id) AS message_count"
            " FROM sessions s LEFT JOIN messages m ON m.session_id = s.id"
            " GROUP BY s.id ORDER BY s.started_at DESC"
        ).fetchall()
    sessions = []
    for row in rows:
        session = dict(row)
        session["persona"] = json.loads(session.pop("persona_json"))
        sessions.append(session)
    return sessions


def full_export():
    """Every session with its complete transcript — for the JSON export."""
    sessions = list_sessions()
    for session in sessions:
        session["messages"] = get_messages(session["id"])
    return sessions
