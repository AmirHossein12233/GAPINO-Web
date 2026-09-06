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
            alter table public.users add column if not exists display_name text
        """)
        conn.execute("""
            alter table public.users add column if not exists status text
        """)
        conn.execute("""
            alter table public.users add column if not exists avatar text
        """)
        conn.execute("""
            update public.users
            set display_name = username
            where display_name is null or display_name = ''
        """)
        conn.execute("""
            update public.users
            set status = 'سلام، من در گپینو هستم'
            where status is null or status = ''
        """)
        conn.execute("""
            update public.users
            set avatar = ''
            where avatar is null
        """)

        conn.execute("""
            create table if not exists public.file_blobs (
                id text primary key,
                owner text not null,
                kind text not null,
                original_name text not null,
                content_type text not null,
                size_bytes bigint not null,
                data bytea not null,
                created_at timestamptz not null default now()
            )
        """)

        conn.execute("""
            create index if not exists idx_file_blobs_owner
            on public.file_blobs(owner)
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
            alter table public.messages add column if not exists file_id text
        """)
        conn.execute("""
            alter table public.messages add column if not exists file_name text
        """)
        conn.execute("""
            alter table public.messages add column if not exists file_type text
        """)
        conn.execute("""
            alter table public.messages add column if not exists file_url text
        """)
        conn.execute("""
            alter table public.messages add column if not exists file_size bigint
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
                select id,sender,receiver,text,created_at,file_id,file_name,file_type,file_url,file_size
                from public.messages
                where (sender=%s and receiver=%s) or (sender=%s and receiver=%s)
                order by created_at asc
            """, (user1, user2, user2, user1)).fetchall()
        else:
            rows = conn.execute("""
                select id,sender,receiver,text,created_at,file_id,file_name,file_type,file_url,file_size
                from public.messages
                order by created_at asc
            """).fetchall()
    return [dict(row) for row in rows]


def db_insert_message(message: dict) -> dict:
    payload = {
        "id": str(message["id"]),
        "sender": str(message["sender"]),
        "receiver": str(message["receiver"]),
        "text": str(message.get("text", "")),
        "created_at": str(message["created_at"]),
        "file_id": message.get("file_id"),
        "file_name": message.get("file_name"),
        "file_type": message.get("file_type"),
        "file_url": message.get("file_url"),
        "file_size": message.get("file_size"),
    }
    with get_conn() as conn:
        row = conn.execute("""
            insert into public.messages (id,sender,receiver,text,created_at,file_id,file_name,file_type,file_url,file_size)
            values (%(id)s,%(sender)s,%(receiver)s,%(text)s,%(created_at)s,%(file_id)s,%(file_name)s,%(file_type)s,%(file_url)s,%(file_size)s)
            on conflict (id) do nothing
            returning id,sender,receiver,text,created_at,file_id,file_name,file_type,file_url,file_size
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


def db_store_file(owner: str, kind: str, original_name: str, content_type: str, data: bytes) -> str:
    init_database()
    import secrets
    file_id = secrets.token_hex(20)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO public.file_blobs
                (id, owner, kind, original_name, content_type, size_bytes, data)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                file_id,
                str(owner),
                str(kind),
                str(original_name),
                str(content_type),
                len(data),
                data,
            ),
        )
    return file_id


def db_get_file(file_id: str) -> Optional[dict]:
    init_database()
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, owner, kind, original_name, content_type, size_bytes, data, created_at
            FROM public.file_blobs
            WHERE id = %s
            """,
            (str(file_id),),
        ).fetchone()
    return dict(row) if row else None


def db_delete_file(file_id: str) -> None:
    if not DATABASE_ENABLED or not file_id:
        return
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM public.file_blobs WHERE id = %s",
            (str(file_id),),
        )
