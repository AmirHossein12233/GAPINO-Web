import json
import os
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


def enabled() -> bool:
    return bool(DATABASE_URL)


def connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")
    return psycopg.connect(DATABASE_URL, connect_timeout=10)


def init_db() -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    profile JSONB NOT NULL DEFAULT '{}'::jsonb
                )
            """)
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower_idx "
                "ON users (LOWER(username))"
            )
            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    sender TEXT NOT NULL,
                    receiver TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS messages_sender_receiver_idx "
                "ON messages (sender, receiver, created_at)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS messages_receiver_sender_idx "
                "ON messages (receiver, sender, created_at)"
            )
        conn.commit()


def migrate_json_once(users_file: Path, messages_file: Path) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            users_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM messages")
            messages_count = cur.fetchone()[0]

            if users_count == 0 and users_file.exists():
                try:
                    users = json.loads(users_file.read_text(encoding="utf-8"))
                except Exception:
                    users = []
                if isinstance(users, list):
                    for user in users:
                        if not isinstance(user, dict):
                            continue
                        username = str(user.get("username", "")).strip()
                        password = str(user.get("password", ""))
                        if not username or not password:
                            continue
                        profile = (
                            user.get("profile")
                            if isinstance(user.get("profile"), dict)
                            else {}
                        )
                        profile.setdefault("display_name", username)
                        profile.setdefault("status", "سلام، من در گپینو هستم")
                        profile.setdefault("avatar", "")
                        created_at = str(user.get("created_at", ""))
                        cur.execute(
                            """
                            INSERT INTO users (username, password, created_at, profile)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (username) DO NOTHING
                            """,
                            (username, password, created_at, Jsonb(profile)),
                        )

            if messages_count == 0 and messages_file.exists():
                try:
                    messages = json.loads(messages_file.read_text(encoding="utf-8"))
                except Exception:
                    messages = []
                if isinstance(messages, list):
                    for message in messages:
                        if not isinstance(message, dict):
                            continue
                        message_id = str(message.get("id", "")).strip()
                        sender = str(message.get("sender", "")).strip()
                        receiver = str(message.get("receiver", "")).strip()
                        text = str(message.get("text", ""))
                        created_at = str(message.get("created_at", ""))
                        if not message_id or not sender or not receiver:
                            continue
                        cur.execute(
                            """
                            INSERT INTO messages (id, sender, receiver, text, created_at)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (id) DO NOTHING
                            """,
                            (message_id, sender, receiver, text, created_at),
                        )
        conn.commit()


def load_users() -> list[dict]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT username, password, created_at, profile FROM users ORDER BY username"
        )
        rows = cur.fetchall()
    return [
        {
            "username": row[0],
            "password": row[1],
            "created_at": row[2],
            "profile": row[3] if isinstance(row[3], dict) else {},
        }
        for row in rows
    ]


def find_user(username: str):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT username, password, created_at, profile "
            "FROM users WHERE LOWER(username)=LOWER(%s) LIMIT 1",
            (username,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "username": row[0],
        "password": row[1],
        "created_at": row[2],
        "profile": row[3] if isinstance(row[3], dict) else {},
    }


def insert_user(user: dict) -> None:
    profile = user.get("profile") if isinstance(user.get("profile"), dict) else {}
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (username, password, created_at, profile)
            VALUES (%s, %s, %s, %s)
            """,
            (
                user["username"],
                user["password"],
                user.get("created_at", ""),
                Jsonb(profile),
            ),
        )
        conn.commit()


def update_user(username: str, *, password=None, created_at=None, profile=None) -> None:
    fields = []
    values = []
    if password is not None:
        fields.append("password=%s")
        values.append(password)
    if created_at is not None:
        fields.append("created_at=%s")
        values.append(created_at)
    if profile is not None:
        fields.append("profile=%s")
        values.append(Jsonb(profile))
    if not fields:
        return
    values.append(username)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE users SET {', '.join(fields)} "
            "WHERE LOWER(username)=LOWER(%s)",
            values,
        )
        conn.commit()


def load_messages() -> list[dict]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, sender, receiver, text, created_at "
            "FROM messages ORDER BY created_at ASC"
        )
        rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "sender": row[1],
            "receiver": row[2],
            "text": row[3],
            "created_at": row[4],
        }
        for row in rows
    ]


def get_private_messages(user1: str, user2: str) -> list[dict]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, sender, receiver, text, created_at
            FROM messages
            WHERE (sender=%s AND receiver=%s)
               OR (sender=%s AND receiver=%s)
            ORDER BY created_at ASC
            """,
            (user1, user2, user2, user1),
        )
        rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "sender": row[1],
            "receiver": row[2],
            "text": row[3],
            "created_at": row[4],
        }
        for row in rows
    ]


def insert_message(message: dict) -> bool:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO messages (id, sender, receiver, text, created_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                message["id"],
                message["sender"],
                message["receiver"],
                message["text"],
                message["created_at"],
            ),
        )
        conn.commit()
        return cur.rowcount == 1
