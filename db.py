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



def init_database() -> None:

    if not DATABASE_ENABLED:
        return


    with get_conn() as conn:

        # کاربران
        conn.execute("""
            CREATE TABLE IF NOT EXISTS public.users (
                username TEXT PRIMARY KEY,
                password TEXT NOT NULL,
                created_at TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'سلام، من در گپینو هستم',
                avatar TEXT NOT NULL DEFAULT ''
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


        conn.execute("""
            UPDATE public.users
            SET display_name=username
            WHERE display_name IS NULL OR display_name=''
        """)


        conn.execute("""
            UPDATE public.users
            SET status='سلام، من در گپینو هستم'
            WHERE status IS NULL OR status=''
        """)


        conn.execute("""
            UPDATE public.users
            SET avatar=''
            WHERE avatar IS NULL
        """)



        # پیام‌ها

        conn.execute("""
            CREATE TABLE IF NOT EXISTS public.messages (

                id TEXT PRIMARY KEY,

                sender TEXT NOT NULL,

                receiver TEXT NOT NULL,

                text TEXT NOT NULL,

                created_at TEXT NOT NULL

            )
        """)


        conn.execute("""
            ALTER TABLE public.messages
            ADD COLUMN IF NOT EXISTS file_id TEXT
        """)


        conn.execute("""
            ALTER TABLE public.messages
            ADD COLUMN IF NOT EXISTS file_name TEXT
        """)


        conn.execute("""
            ALTER TABLE public.messages
            ADD COLUMN IF NOT EXISTS file_type TEXT
        """)


        conn.execute("""
            ALTER TABLE public.messages
            ADD COLUMN IF NOT EXISTS file_url TEXT
        """)


        conn.execute("""
            ALTER TABLE public.messages
            ADD COLUMN IF NOT EXISTS file_size BIGINT
        """)



        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_pair_time

            ON public.messages(sender,receiver,created_at)

        """)



        # فایل‌های دائمی

        conn.execute("""
            CREATE TABLE IF NOT EXISTS public.file_blobs (

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



        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_file_blobs_owner

            ON public.file_blobs(owner)

        """)




        # پخش زنده گپینو

        conn.execute("""
            CREATE TABLE IF NOT EXISTS public.live_streams (

                id TEXT PRIMARY KEY,

                host TEXT NOT NULL,

                title TEXT NOT NULL,

                description TEXT NOT NULL DEFAULT '',

                status TEXT NOT NULL DEFAULT 'offline',

                viewers INTEGER NOT NULL DEFAULT 0,

                created_at TIMESTAMPTZ DEFAULT now()

            )
        """)



        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_live_streams_status

            ON public.live_streams(status)

        """)



        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_live_streams_host

            ON public.live_streams(host)

        """)




        # بینندگان لایو

        conn.execute("""
            CREATE TABLE IF NOT EXISTS public.live_viewers (

                id TEXT PRIMARY KEY,

                stream_id TEXT NOT NULL,

                username TEXT NOT NULL,

                joined_at TIMESTAMPTZ DEFAULT now()

            )
        """)



        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_live_viewers_stream

            ON public.live_viewers(stream_id)

        """)
def _user_from_row(row: Optional[dict]) -> Optional[dict]:

    if not row:
        return None

    return {
        "username": row["username"],
        "password": row["password"],
        "created_at": str(row["created_at"]),
        "profile": {
            "display_name": row.get("display_name") or row["username"],
            "status": row.get("status") or "سلام، من در گپینو هستم",
            "avatar": row.get("avatar") or "",
        }
    }



def db_get_user(username: str):

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



def db_list_users():

    init_database()

    with get_conn() as conn:

        rows = conn.execute(
            """
            SELECT
                username,
                password,
                created_at,
                display_name,
                status,
                avatar
            FROM public.users
            ORDER BY created_at,username
            """
        ).fetchall()


    return [
        _user_from_row(row)
        for row in rows
    ]



def db_upsert_user(user: dict):

    init_database()

    profile = user.get("profile", {})


    data = {

        "username": user["username"],

        "password": user["password"],

        "created_at": str(
            user.get("created_at")
            or datetime.now(timezone.utc).isoformat()
        ),

        "display_name": profile.get(
            "display_name",
            user["username"]
        ),

        "status": profile.get(
            "status",
            "سلام، من در گپینو هستم"
        ),

        "avatar": profile.get(
            "avatar",
            ""
        )
    }



    with get_conn() as conn:

        row = conn.execute(
            """
            INSERT INTO public.users
            (
                username,
                password,
                created_at,
                display_name,
                status,
                avatar
            )
            VALUES
            (
                %(username)s,
                %(password)s,
                %(created_at)s,
                %(display_name)s,
                %(status)s,
                %(avatar)s
            )

            ON CONFLICT(username)
            DO UPDATE SET

                password=EXCLUDED.password,

                display_name=EXCLUDED.display_name,

                status=EXCLUDED.status,

                avatar=EXCLUDED.avatar

            RETURNING *
            """,
            data
        ).fetchone()


    return _user_from_row(row)




# ======================
# پیام‌ها
# ======================


def db_get_messages(user1=None,user2=None):

    init_database()


    with get_conn() as conn:

        if user1 and user2:

            rows = conn.execute(
                """
                SELECT *
                FROM public.messages

                WHERE
                (sender=%s AND receiver=%s)

                OR

                (sender=%s AND receiver=%s)

                ORDER BY created_at ASC
                """,
                (
                    user1,
                    user2,
                    user2,
                    user1
                )
            ).fetchall()

        else:

            rows = conn.execute(
                """
                SELECT *
                FROM public.messages
                ORDER BY created_at ASC
                """
            ).fetchall()


    return [
        dict(row)
        for row in rows
    ]





def db_insert_message(message: dict):

    init_database()


    with get_conn() as conn:

        row = conn.execute(
            """
            INSERT INTO public.messages
            (
                id,
                sender,
                receiver,
                text,
                created_at,
                file_id,
                file_name,
                file_type,
                file_url,
                file_size
            )

            VALUES

            (
                %(id)s,
                %(sender)s,
                %(receiver)s,
                %(text)s,
                %(created_at)s,
                %(file_id)s,
                %(file_name)s,
                %(file_type)s,
                %(file_url)s,
                %(file_size)s
            )

            ON CONFLICT(id)
            DO NOTHING

            RETURNING *
            """,
            message
        ).fetchone()


    return dict(row) if row else message




# ======================
# فایل دائمی
# ======================


def db_store_file(
    owner,
    kind,
    original_name,
    content_type,
    data
):

    init_database()

    import secrets

    file_id = secrets.token_hex(20)


    with get_conn() as conn:

        conn.execute(
            """
            INSERT INTO public.file_blobs
            (
                id,
                owner,
                kind,
                original_name,
                content_type,
                size_bytes,
                data
            )

            VALUES
            (
                %s,%s,%s,%s,%s,%s,%s
            )
            """,
            (
                file_id,
                owner,
                kind,
                original_name,
                content_type,
                len(data),
                data
            )
        )


    return file_id




def db_get_file(file_id):

    init_database()

    with get_conn() as conn:

        row = conn.execute(
            """
            SELECT *
            FROM public.file_blobs
            WHERE id=%s
            """,
            (file_id,)
        ).fetchone()


    return dict(row) if row else None




# ======================
# پخش زنده گپینو
# ======================


def db_create_live(host,title,description=""):

    init_database()

    import secrets

    live_id = secrets.token_hex(12)


    with get_conn() as conn:

        row = conn.execute(
            """
            INSERT INTO public.live_streams
            (
                id,
                host,
                title,
                description,
                status
            )

            VALUES
            (
                %s,%s,%s,%s,'online'
            )

            RETURNING *
            """,
            (
                live_id,
                host,
                title,
                description
            )
        ).fetchone()


    return dict(row)




def db_list_live():

    init_database()

    with get_conn() as conn:

        rows = conn.execute(
            """
            SELECT *
            FROM public.live_streams
            WHERE status='online'
            ORDER BY created_at DESC
            """
        ).fetchall()


    return [
        dict(row)
        for row in rows
    ]




def db_stop_live(stream_id):

    init_database()

    with get_conn() as conn:

        conn.execute(
            """
            UPDATE public.live_streams

            SET status='offline'

            WHERE id=%s
            """,
            (stream_id,)
        )




def db_join_live(stream_id,username):

    init_database()

    import secrets

    viewer_id = secrets.token_hex(12)


    with get_conn() as conn:

        conn.execute(
            """
            INSERT INTO public.live_viewers
            (
                id,
                stream_id,
                username
            )

            VALUES
            (
                %s,%s,%s
            )
            """,
            (
                viewer_id,
                stream_id,
                username
            )
        )


        conn.execute(
            """
            UPDATE public.live_streams

            SET viewers=viewers+1

            WHERE id=%s
            """,
            (stream_id,)
        )




def db_leave_live(stream_id,username):

    init_database()

    with get_conn() as conn:

        conn.execute(
            """
            DELETE FROM public.live_viewers

            WHERE
            stream_id=%s

            AND

            username=%s
            """,
            (
                stream_id,
                username
            )
        )


        conn.execute(
            """
            UPDATE public.live_streams

            SET viewers=
            CASE
                WHEN viewers>0 THEN viewers-1
                ELSE 0
            END

            WHERE id=%s
            """,
            (stream_id,)
        )