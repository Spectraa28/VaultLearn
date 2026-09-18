"""SQLite persistence for demo sessions and agent run history."""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect():
    conn = sqlite3.connect(os.getenv("VAULTLEARN_DB_PATH", "sessions.db"), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    with _connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY, url TEXT, title TEXT, created_at TEXT,
            collection_name TEXT, study_plan_json TEXT
        )""")
        existing = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
        for name, definition in {
            "current_module_number": "INTEGER NOT NULL DEFAULT 1",
            "struggle_signals_json": "TEXT NOT NULL DEFAULT '{}'",
            "notes_written": "INTEGER NOT NULL DEFAULT 0",
            "updated_at": "TEXT",
            "pending_quiz_json": "TEXT NOT NULL DEFAULT '{}'",
            "mastery_scores_json": "TEXT NOT NULL DEFAULT '{}'",
            "index_report_json": "TEXT NOT NULL DEFAULT '{}'",
        }.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} {definition}")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                role TEXT NOT NULL, content TEXT NOT NULL, citations_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL, FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, id);
            CREATE TABLE IF NOT EXISTS agent_runs (
                run_id TEXT PRIMARY KEY, session_id TEXT, kind TEXT NOT NULL,
                status TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT,
                error_type TEXT, FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            );
            CREATE TABLE IF NOT EXISTS agent_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                session_id TEXT, name TEXT NOT NULL, status TEXT NOT NULL,
                duration_ms REAL, details_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_run ON agent_events(run_id, id);
            CREATE TABLE IF NOT EXISTS llm_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                session_id TEXT, operation TEXT NOT NULL, provider TEXT NOT NULL,
                model TEXT NOT NULL, status TEXT NOT NULL, input_tokens INTEGER,
                output_tokens INTEGER, estimated_cost_usd REAL, duration_ms REAL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_usage_session ON llm_usage(session_id, id);
        """)


def create_session(session_id, url, title, collection_name, study_plan_json, index_report=None):
    init_db()
    with _connect() as conn:
        conn.execute("""INSERT INTO sessions
            (session_id, url, title, created_at, collection_name, study_plan_json, updated_at, index_report_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, url, title, _now(), collection_name, study_plan_json, _now(), json.dumps(index_report or {})))


def list_sessions():
    init_db()
    with _connect() as conn:
        rows = conn.execute("SELECT session_id, url, title, created_at, updated_at FROM sessions ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]


def get_session(session_id):
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        return dict(row) if row else None


def get_turns(session_id):
    with _connect() as conn:
        rows = conn.execute("SELECT role, content, citations_json, created_at FROM turns WHERE session_id = ? ORDER BY id", (session_id,)).fetchall()
        return [{**dict(row), "citations": json.loads(row["citations_json"])} for row in rows]


def save_turn(session_id, role, content, citations=None):
    with _connect() as conn:
        conn.execute("INSERT INTO turns(session_id, role, content, citations_json, created_at) VALUES (?, ?, ?, ?, ?)",
                     (session_id, role, content, json.dumps(citations or []), _now()))


def update_session(session_id, module_number, struggle_signals, notes_written, pending_quiz=None, mastery_scores=None):
    with _connect() as conn:
        conn.execute("""UPDATE sessions SET current_module_number = ?, struggle_signals_json = ?,
            notes_written = ?, pending_quiz_json = ?, mastery_scores_json = ?, updated_at = ? WHERE session_id = ?""",
            (module_number, json.dumps(struggle_signals or {}), int(bool(notes_written)),
             json.dumps(pending_quiz or {}), json.dumps(mastery_scores or {}), _now(), session_id))


def save_exchange(session_id, user_text, assistant_text, citations, module_number,
                  struggle_signals, notes_written, pending_quiz, mastery_scores):
    """Commit both messages and the resulting session checkpoint together."""
    now = _now()
    with _connect() as conn:
        conn.execute("INSERT INTO turns(session_id, role, content, citations_json, created_at) VALUES (?, 'user', ?, '[]', ?)",
                     (session_id, user_text, now))
        conn.execute("INSERT INTO turns(session_id, role, content, citations_json, created_at) VALUES (?, 'assistant', ?, ?, ?)",
                     (session_id, assistant_text, json.dumps(citations or []), now))
        conn.execute("""UPDATE sessions SET current_module_number = ?, struggle_signals_json = ?,
            notes_written = ?, pending_quiz_json = ?, mastery_scores_json = ?, updated_at = ? WHERE session_id = ?""",
            (module_number, json.dumps(struggle_signals or {}), int(bool(notes_written)),
             json.dumps(pending_quiz or {}), json.dumps(mastery_scores or {}), now, session_id))


def start_run(run_id, kind, session_id=None):
    init_db()
    with _connect() as conn:
        conn.execute("INSERT INTO agent_runs(run_id, session_id, kind, status, started_at) VALUES (?, ?, ?, 'running', ?)",
                     (run_id, session_id, kind, _now()))


def mark_abandoned_runs():
    """Single-process demo recovery: runs left running by a restart are interrupted."""
    with _connect() as conn:
        conn.execute("""UPDATE agent_runs SET status = 'interrupted', completed_at = ?,
            error_type = 'ProcessRestart' WHERE status = 'running'""", (_now(),))


def finish_run(run_id, status, error_type=None, session_id=None):
    with _connect() as conn:
        conn.execute("UPDATE agent_runs SET status = ?, completed_at = ?, error_type = ?, session_id = COALESCE(session_id, ?) WHERE run_id = ?",
                     (status, _now(), error_type, session_id, run_id))


def attach_run_to_session(run_id, session_id):
    with _connect() as conn:
        conn.execute("UPDATE agent_events SET session_id = ? WHERE run_id = ?", (session_id, run_id))
        conn.execute("UPDATE llm_usage SET session_id = ? WHERE run_id = ?", (session_id, run_id))


def add_event(run_id, session_id, name, status, duration_ms, details):
    with _connect() as conn:
        conn.execute("""INSERT INTO agent_events(run_id, session_id, name, status, duration_ms, details_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""", (run_id, session_id, name, status, duration_ms, json.dumps(details), _now()))


def add_usage(run_id, session_id, operation, model, status, input_tokens, output_tokens, cost, duration_ms):
    with _connect() as conn:
        conn.execute("""INSERT INTO llm_usage(run_id, session_id, operation, provider, model, status,
            input_tokens, output_tokens, estimated_cost_usd, duration_ms, created_at)
            VALUES (?, ?, ?, 'groq', ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, session_id, operation, model, status, input_tokens, output_tokens, cost, duration_ms, _now()))


def get_trace(run_id):
    with _connect() as conn:
        run = conn.execute("SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)).fetchone()
        if not run:
            return None
        events = conn.execute("SELECT name, status, duration_ms, details_json, created_at FROM agent_events WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
        return {"run": dict(run), "events": [{**dict(e), "details": json.loads(e["details_json"])} for e in events]}


def get_runs(session_id):
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM agent_runs WHERE session_id = ? ORDER BY started_at DESC", (session_id,)).fetchall()
        return [dict(row) for row in rows]


def get_usage(session_id=None):
    with _connect() as conn:
        where = "WHERE session_id = ?" if session_id else ""
        args = (session_id,) if session_id else ()
        rows = conn.execute(f"SELECT * FROM llm_usage {where} ORDER BY id DESC", args).fetchall()
        totals = conn.execute(f"""SELECT COUNT(*) AS calls, COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd
            FROM llm_usage {where}""", args).fetchone()
        return {"totals": dict(totals), "calls": [dict(row) for row in rows]}
