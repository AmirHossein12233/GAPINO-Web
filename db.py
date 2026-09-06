import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DATABASE_ENABLED = bool(DATABASE_URL)


def _normalize_db_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


if DATABASE_ENABLED:
    DATABASE_URL = _normalize_db_url(DATABASE_URL)


@contextmanager
def get_conn() -> Iterator[object]:
    if not DATABASE_ENABLED:
        raise RuntimeError("DATABASE_URL is not configured")
    import psycopg
    from psycopg.rows import dict_row
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_database() -> None:
    if not DATABASE_ENABLED:
        return
    with get_conn() as conn:
        conn.execute("""
            create table if not exists public.users (
                username text primary key,
                password text not null,
                created_at text not null,
                display_name text not null default '',
                status text not null default 'سلام، من در گپینو هستم',
                avatar text not null default ''
            )
        """)
        conn.execute("""
            create table if not exists public.messages (
                id text primary key,
                sender text not null,
                receiver text not null,
                text text not null,
                created_at text not null
            )
        """)
        conn.execute("""
            create index if not exists idx_messages_pair_time
            on public.messages(sender, receiver, created_at)
        """)
        conn.execute("""
            create index if not exists idx_messages_created_at
            on public.messages(created_at)
        """)


def _user_from_row(row: Optional[dict]) -> Optional[dict]:
    if not row:
        return None
    return {
        "username": row["username"],
        "password": row["password"],
        "created_at": row["created_at"],
        "profile": {
            "display_name": row.get("display_name") or row["username"],
            "status": row.get("status") or "سلام، من در گپینو هستم",
            "avatar": row.get("avatar") or "",
        },
    }


def db_get_user(username: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "select username,password,created_at,display_name,status,avatar from public.users where username=%s",
            (username,),
        ).fetchone()
    return _user_from_row(row)


def db_list_users() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "select username,password,created_at,display_name,status,avatar from public.users order by created_at, username"
        ).fetchall()
    return [_user_from_row(row) for row in rows]


def db_upsert_user(user: dict) -> dict:
    profile = user.get("profile") if isinstance(user.get("profile"), dict) else {}
    username = str(user.get("username", "")).strip()
    if not username:
        raise ValueError("username is required")
    payload = {
        "username": username,
        "password": str(user.get("password", "")),
        "created_at": str(user.get("created_at") or datetime.now(timezone.utc).isoformat()),
        "display_name": str(profile.get("display_name") or username),
        "status": str(profile.get("status") or "سلام، من در گپینو هستم"),
        "avatar": str(profile.get("avatar") or ""),
    }
    with get_conn() as conn:
        row = conn.execute("""
            insert into public.users (username,password,created_at,display_name,status,avatar)
            values (%(username)s,%(password)s,%(created_at)s,%(display_name)s,%(status)s,%(avatar)s)
            on conflict (username) do update set
                password=excluded.password,
                created_at=excluded.created_at,
                display_name=excluded.display_name,
                status=excluded.status,
                avatar=excluded.avatar
            returning username,password,created_at,display_name,status,avatar
        """, payload).fetchone()
    return _user_from_row(row)


def db_update_user(username: str, *, status: Optional[str] = None, profile: Optional[dict] = None) -> Optional[dict]:
    current = db_get_user(username)
    if not current:
        return None
    if profile is not None:
        current["profile"] = profile
    if status is not None:
        current["profile"]["status"] = status
    return db_upsert_user(current)


def db_get_messages(user1: Optional[str] = None, user2: Optional[str] = None) -> list[dict]:
    with get_conn() as conn:
        if user1 is not None and user2 is not None:
            rows = conn.execute("""
                select id,sender,receiver,text,created_at
                from public.messages
                where (sender=%s and receiver=%s) or (sender=%s and receiver=%s)
                order by created_at asc
            """, (user1, user2, user2, user1)).fetchall()
        else:
            rows = conn.execute("""
                select id,sender,receiver,text,created_at
                from public.messages
                order by created_at asc
            """).fetchall()
    return [dict(row) for row in rows]


def db_insert_message(message: dict) -> dict:
    payload = {
        "id": str(message["id"]),
        "sender": str(message["sender"]),
        "receiver": str(message["receiver"]),
        "text": str(message["text"]),
        "created_at": str(message["created_at"]),
    }
    with get_conn() as conn:
        row = conn.execute("""
            insert into public.messages (id,sender,receiver,text,created_at)
            values (%(id)s,%(sender)s,%(receiver)s,%(text)s,%(created_at)s)
            on conflict (id) do nothing
            returning id,sender,receiver,text,created_at
        """, payload).fetchone()
    return dict(row) if row else payload


def migrate_json_to_database(users_file: Path, messages_file: Path) -> None:
    if not DATABASE_ENABLED:
        return

    def read_json(path: Path, default):
        try:
            with path.open("r", encoding="utf-8") as f:
                value = json.load(f)
            return value if isinstance(value, type(default)) else default
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return default

    users = read_json(users_file, [])
    messages = read_json(messages_file, [])

    if users:
        for user in users:
            if isinstance(user, dict) and user.get("username"):
                # Preserve old JSON records while making them DB-backed.
                db_upsert_user(user)

    if messages:
        for message in messages:
            if not isinstance(message, dict):
                continue
            if all(message.get(k) for k in ("id", "sender", "receiver", "text", "created_at")):
                db_insert_message(message)
