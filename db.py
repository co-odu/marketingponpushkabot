# db.py — слой хранения заявок в SQLite

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

DB_PATH = "requests.db"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Создаёт таблицу заявок, если её ещё нет"""
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS requests (
                request_id      TEXT PRIMARY KEY,
                user_id         INTEGER NOT NULL,
                status          TEXT NOT NULL DEFAULT 'pending',
                reason          TEXT,
                company         TEXT,
                object          TEXT,
                task_date       TEXT,
                tech_task       TEXT,
                print_type      TEXT,
                size            TEXT,
                deadline_str    TEXT,
                is_urgent       INTEGER,
                admin_chat_id   INTEGER,
                admin_message_id INTEGER,
                created_at      TEXT
            )
            """
        )


def create_request(
    request_id: str,
    user_id: int,
    company: str,
    object_: str,
    task_date: datetime,
    tech_task: str,
    print_type: str,
    size: str,
    deadline_str: str,
    is_urgent: bool,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO requests (
                request_id, user_id, status, reason,
                company, object, task_date, tech_task, print_type, size,
                deadline_str, is_urgent, admin_chat_id, admin_message_id, created_at
            ) VALUES (?, ?, 'pending', NULL, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
            """,
            (
                request_id,
                user_id,
                company,
                object_,
                task_date.isoformat(),
                tech_task,
                print_type,
                size,
                deadline_str,
                int(is_urgent),
                datetime.now().isoformat(),
            ),
        )


def set_admin_message(request_id: str, admin_chat_id: int, admin_message_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE requests SET admin_chat_id = ?, admin_message_id = ? WHERE request_id = ?",
            (admin_chat_id, admin_message_id, request_id),
        )


def set_status(request_id: str, status: str, reason: Optional[str] = None) -> None:
    with get_conn() as conn:
        if reason is not None:
            conn.execute(
                "UPDATE requests SET status = ?, reason = ? WHERE request_id = ?",
                (status, reason, request_id),
            )
        else:
            conn.execute(
                "UPDATE requests SET status = ? WHERE request_id = ?",
                (status, request_id),
            )


def get_request(request_id: str) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM requests WHERE request_id = ?", (request_id,))
        return cur.fetchone()


def get_requests_by_user(user_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM requests WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        return cur.fetchall()
