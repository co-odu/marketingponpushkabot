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
    """Создаёт таблицы, если их ещё нет, и докатывает миграции для старых БД"""
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
                work_format     TEXT,
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
        # Миграция для БД, созданных до появления поля work_format
        existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(requests)")}
        if "work_format" not in existing_columns:
            conn.execute("ALTER TABLE requests ADD COLUMN work_format TEXT")

        # Заявка теперь может быть отправлена НЕСКОЛЬКИМ админам одновременно —
        # тут храним по одной строке на каждое такое сообщение, чтобы потом
        # можно было обновить/отредактировать все разом.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_messages (
                request_id  TEXT NOT NULL,
                chat_id     INTEGER NOT NULL,
                message_id  INTEGER NOT NULL,
                PRIMARY KEY (request_id, chat_id)
            )
            """
        )


def create_request(
    request_id: str,
    user_id: int,
    company: str,
    object_: str,
    task_date: datetime,
    work_format: str,
    tech_task: str,
    print_type: str,
    size: str,
    deadline_str: str,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO requests (
                request_id, user_id, status, reason,
                company, object, task_date, work_format, tech_task, print_type, size,
                deadline_str, is_urgent, admin_chat_id, admin_message_id, created_at
            ) VALUES (?, ?, 'pending', NULL, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, ?)
            """,
            (
                request_id,
                user_id,
                company,
                object_,
                task_date.isoformat(),
                work_format,
                tech_task,
                print_type,
                size,
                deadline_str,
                datetime.now().isoformat(),
            ),
        )


def set_admin_message(request_id: str, admin_chat_id: int, admin_message_id: int) -> None:
    """Оставлено для обратной совместимости — пишет в основную таблицу первое сообщение."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE requests SET admin_chat_id = ?, admin_message_id = ? WHERE request_id = ?",
            (admin_chat_id, admin_message_id, request_id),
        )


def add_admin_message(request_id: str, chat_id: int, message_id: int) -> None:
    """Регистрирует ещё одно сообщение у конкретного админа для этой заявки
    (используется, когда заявка/карточка разослана нескольким админам)."""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO admin_messages (request_id, chat_id, message_id) VALUES (?, ?, ?)",
            (request_id, chat_id, message_id),
        )


def get_admin_messages(request_id: str) -> list[sqlite3.Row]:
    """Возвращает все сообщения у админов, связанные с этой заявкой"""
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT chat_id, message_id FROM admin_messages WHERE request_id = ?",
            (request_id,),
        )
        return cur.fetchall()


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


def get_requests_by_status(status: str) -> list[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM requests WHERE status = ? ORDER BY created_at DESC",
            (status,),
        )
        return cur.fetchall()
