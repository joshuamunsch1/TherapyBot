"""Postgres persistence for sessions and messages.

The database deliberately lives outside the web service. Render's free plan has
an ephemeral filesystem and spins the service down after 15 minutes of idle
time, which wipes anything stored locally, so a local SQLite file would lose
transcripts constantly. Any Postgres works: Neon, Supabase, Render Postgres, or
one you run yourself. The connection string comes from DATABASE_URL.
"""

import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()

# One connection per gunicorn thread at peak: a thread holds a connection only
# while it reads or writes, never while waiting on the model.
POOL_MAX_SIZE = int(os.environ.get("THERAPYBOT_DB_POOL_SIZE", "8"))

MISSING_URL_MESSAGE = (
    "DATABASE_URL is not set. TherapyBot keeps transcripts in Postgres so they "
    "survive restarts. Create a free database (for example at neon.tech) and put "
    "its connection string in DATABASE_URL."
)

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        student_name TEXT NOT NULL,
        language TEXT NOT NULL,
        disorder_id TEXT NOT NULL,
        persona_json TEXT NOT NULL,
        started_at TEXT NOT NULL,
        diagnosis_guess TEXT,
        diagnosis_correct BOOLEAN,
        justification TEXT,
        diagnosed_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS messages (
        id BIGSERIAL PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES sessions(id),
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)",
]

_pool = None


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_pool():
    """The process-wide connection pool, created on first use."""
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError(MISSING_URL_MESSAGE)
        _pool = ConnectionPool(
            DATABASE_URL,
            min_size=1,
            max_size=POOL_MAX_SIZE,
            kwargs={"row_factory": dict_row},
            # Serverless Postgres (Neon, Supabase) drops idle connections when it
            # suspends. Test one before handing it out, so the first student back
            # after a quiet spell gets a fresh connection instead of an error.
            check=ConnectionPool.check_connection,
            # Fail a request in 10s rather than the 30s default, so a database
            # that is down surfaces a clear error instead of a hung page.
            timeout=10,
            open=True,
        )
    return _pool


@contextmanager
def connect():
    """A pooled connection: commits on clean exit, rolls back on exception."""
    with get_pool().connection() as conn:
        yield conn


def init_db(attempts=5):
    """Create the tables, retrying while a suspended database wakes up."""
    if not DATABASE_URL:
        raise RuntimeError(MISSING_URL_MESSAGE)
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            with connect() as conn:
                for statement in SCHEMA:
                    conn.execute(statement)
            return
        except Exception as error:  # connection refused, pool timeout, cold start
            last_error = error
            if attempt < attempts:
                time.sleep(min(2 ** attempt, 15))
    raise RuntimeError(
        f"Could not reach the database after {attempts} attempts. "
        f"Check DATABASE_URL. Last error: {last_error}"
    ) from last_error


def create_session(student_name, language, disorder_id, persona):
    session_id = uuid.uuid4().hex
    with connect() as conn:
        conn.execute(
            "INSERT INTO sessions (id, student_name, language, disorder_id, persona_json, started_at)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (session_id, student_name, language, disorder_id, json.dumps(persona), _now()),
        )
    return session_id


def get_session(session_id):
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = %s", (session_id,)
        ).fetchone()
    if row is None:
        return None
    session = dict(row)
    session["persona"] = json.loads(session.pop("persona_json"))
    return session


def add_message(session_id, role, content):
    with connect() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (%s, %s, %s, %s)",
            (session_id, role, content, _now()),
        )


def get_messages(session_id):
    with connect() as conn:
        rows = conn.execute(
            "SELECT role, content, created_at FROM messages WHERE session_id = %s ORDER BY id",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def count_user_messages(session_id):
    """Number of student turns so far - used to enforce the per-session cap."""
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE session_id = %s AND role = 'user'",
            (session_id,),
        ).fetchone()
    return row["n"]


def record_diagnosis(session_id, guess, correct, justification):
    with connect() as conn:
        conn.execute(
            "UPDATE sessions SET diagnosis_guess = %s, diagnosis_correct = %s,"
            " justification = %s, diagnosed_at = %s WHERE id = %s",
            (guess, bool(correct), justification, _now(), session_id),
        )


def list_sessions():
    """All sessions, newest first, with message counts - for the admin page."""
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
    """Every session with its complete transcript - for the JSON export.

    Messages are fetched in one query rather than one per session: the database
    is now across the network, where a few hundred round trips would be slow.
    """
    sessions = list_sessions()
    by_session = {s["id"]: [] for s in sessions}
    with connect() as conn:
        rows = conn.execute(
            "SELECT session_id, role, content, created_at FROM messages ORDER BY id"
        ).fetchall()
    for row in rows:
        bucket = by_session.get(row["session_id"])
        if bucket is not None:
            bucket.append({
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"],
            })
    for session in sessions:
        session["messages"] = by_session[session["id"]]
    return sessions
