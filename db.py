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

    conn = psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row
    )

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()



def init_database():

    if not DATABASE_ENABLED:
        return


    with get_conn() as conn:

        # USERS

        conn.execute("""
        CREATE TABLE IF NOT EXISTS public.users(
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            created_at TEXT NOT NULL,
            display_name TEXT DEFAULT '',
            status TEXT DEFAULT 'سلام، من در گپینو هستم',
            avatar TEXT DEFAULT ''
        )
        """)


        conn.execute("""
        ALTER TABLE public.users
        ADD COLUMN IF NOT EXISTS display_name TEXT
        """)

        conn.execute("""
        ALTER TABLE public.users
        ADD COLUMN IF NOT EXISTS status TEXT
        """)

        conn.execute("""
        ALTER TABLE public.users
        ADD COLUMN IF NOT EXISTS avatar TEXT
        """)



        # FILE STORAGE

        conn.execute("""
        CREATE TABLE IF NOT EXISTS public.file_blobs(

            id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            kind TEXT NOT NULL,
            original_name TEXT NOT NULL,
            content_type TEXT NOT NULL,
            size_bytes BIGINT NOT NULL,
            data BYTEA NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now()

        )
        """)



        # MESSAGES

        conn.execute("""
        CREATE TABLE IF NOT EXISTS public.messages(

            id TEXT PRIMARY KEY,
            sender TEXT NOT NULL,
            receiver TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            file_id TEXT,
            file_name TEXT,
            file_type TEXT,
            file_url TEXT,
            file_size BIGINT

        )
        """)



        # LIVE STREAM TABLE

        conn.execute("""
        CREATE TABLE IF NOT EXISTS public.live_rooms(

            id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT DEFAULT 'offline',

            stream_key TEXT NOT NULL,

            viewers INTEGER DEFAULT 0,

            created_at TIMESTAMPTZ DEFAULT now(),

            started_at TIMESTAMPTZ

        )
        """)


        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_live_owner
        ON public.live_rooms(owner)
        """)


        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_live_status
        ON public.live_rooms(status)
        """)



        # LIVE VIEWERS

        conn.execute("""
        CREATE TABLE IF NOT EXISTS public.live_viewers(

            id TEXT PRIMARY KEY,

            live_id TEXT NOT NULL,

            username TEXT NOT NULL,

            joined_at TIMESTAMPTZ DEFAULT now()

        )
        """)



        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_live_viewers_room
        ON public.live_viewers(live_id)
        """)




def _user_from_row(row):

    if not row:
        return None


    return {

        "username": row["username"],

        "password": row["password"],

        "created_at": row["created_at"],

        "profile": {

            "display_name":
                row.get("display_name")
                or row["username"],


            "status":
                row.get("status")
                or "سلام، من در گپینو هستم",


            "avatar":
                row.get("avatar")
                or ""

        }

    }



def db_get_user(username):

    init_database()

    with get_conn() as conn:

        row = conn.execute(
        """
        SELECT
        username,
        password,
        created_at,
        display_name,
        status,
        avatar

        FROM public.users

        WHERE username=%s
        """,
        (username,)
        ).fetchone()


    return _user_from_row(row)
# =========================
# LIVE STREAM DATABASE
# =========================

def init_live_database():
    if not DATABASE_ENABLED:
        return

    with get_conn() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS public.live_streams (
                id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'offline',
                stream_key TEXT NOT NULL,
                viewers INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                started_at TIMESTAMPTZ
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_live_owner
            ON public.live_streams(owner)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_live_status
            ON public.live_streams(status)
        """)


def db_create_live(
    owner: str,
    title: str,
    description: str = ""
) -> dict:

    init_live_database()

    import secrets

    live_id = secrets.token_hex(12)
    stream_key = secrets.token_hex(24)

    with get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO public.live_streams
            (
                id,
                owner,
                title,
                description,
                status,
                stream_key
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s,
                'offline',
                %s
            )
            RETURNING *
            """,
            (
                live_id,
                owner,
                title,
                description,
                stream_key,
            ),
        ).fetchone()

    return dict(row)


def db_start_live(live_id: str):

    init_live_database()

    with get_conn() as conn:
        row = conn.execute(
            """
            UPDATE public.live_streams
            SET
                status='live',
                started_at=now()
            WHERE id=%s
            RETURNING *
            """,
            (live_id,),
        ).fetchone()

    return dict(row) if row else None



def db_stop_live(live_id: str):

    init_live_database()

    with get_conn() as conn:
        row = conn.execute(
            """
            UPDATE public.live_streams
            SET
                status='offline',
                viewers=0
            WHERE id=%s
            RETURNING *
            """,
            (live_id,),
        ).fetchone()

    return dict(row) if row else None



def db_get_live(live_id: str):

    init_live_database()

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM public.live_streams
            WHERE id=%s
            """,
            (live_id,),
        ).fetchone()

    return dict(row) if row else None



def db_get_active_lives():

    init_live_database()

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM public.live_streams
            WHERE status='live'
            ORDER BY started_at DESC
            """
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]



def db_update_live_viewers(
    live_id: str,
    viewers: int
):

    init_live_database()

    with get_conn() as conn:
        conn.execute(
            """
            UPDATE public.live_streams
            SET viewers=%s
            WHERE id=%s
            """,
            (
                int(viewers),
                live_id,
            ),
        )



def db_delete_live(live_id: str):

    init_live_database()

    with get_conn() as conn:
        conn.execute(
            """
            DELETE FROM public.live_streams
            WHERE id=%s
            """,
            (live_id,),
        )