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
        row_factory=dict_row,
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
        # ساخت جدول users در صورت نبودن
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS public.users (
                username TEXT PRIMARY KEY,
                password TEXT NOT NULL,
                created_at TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'سلام، من در گپینو هستم',
                avatar TEXT NOT NULL DEFAULT ''
            )
            """
        )

        # مهم:
        # اگر جدول قبلاً ساخته شده باشد، CREATE TABLE IF NOT EXISTS
        # ستون‌های جدید را اضافه نمی‌کند.
        # بنابراین ستون‌ها را صریحاً اضافه می‌کنیم.
        conn.execute(
            """
            ALTER TABLE public.users
            ADD COLUMN IF NOT EXISTS display_name TEXT
            """
        )

        conn.execute(
            """
            ALTER TABLE public.users
            ADD COLUMN IF NOT EXISTS status TEXT
            """
        )

        conn.execute(
            """
            ALTER TABLE public.users
            ADD COLUMN IF NOT EXISTS avatar TEXT
            """
        )

        # پر کردن مقادیر NULL در داده‌های قدیمی
        conn.execute(
            """
            UPDATE public.users
            SET display_name = username
            WHERE display_name IS NULL OR display_name = ''
            """
        )

        conn.execute(
            """
            UPDATE public.users
            SET status = 'سلام، من در گپینو هستم'
            WHERE status IS NULL OR status = ''
            """
        )

        conn.execute(
            """
            UPDATE public.users
            SET avatar = ''
            WHERE avatar IS NULL
            """
        )

        # ساخت جدول پیام‌ها
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS public.messages (
                id TEXT PRIMARY KEY,
                sender TEXT NOT NULL,
                receiver TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_messages_pair_time
            ON public.messages(sender, receiver, created_at)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_messages_created_at
            ON public.messages(created_at)
            """
        )


def _user_from_row(row: Optional[dict]) -> Optional[dict]:
    if not row:
        return None

    return {
        "username": row["username"],
        "password": row["password"],
        "created_at": str(row["created_at"]),
        "profile": {
            "display_name": (
                row.get("display_name")
                or row["username"]
            ),
            "status": (
                row.get("status")
                or "سلام، من در گپینو هستم"
            ),
            "avatar": row.get("avatar") or "",
        },
    }


def db_get_user(username: str) -> Optional[dict]:
    # برای اطمینان، قبل از Query ساختار DB بررسی می‌شود.
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
            WHERE username = %s
            """,
            (username,),
        ).fetchone()

    return _user_from_row(row)


def db_list_users() -> list[dict]:
    # برای اطمینان از وجود ستون‌های جدید
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
            ORDER BY created_at, username
            """
        ).fetchall()

    return [
        _user_from_row(row)
        for row in rows
        if row
    ]


def db_upsert_user(user: dict) -> dict:
    profile = (
        user.get("profile")
        if isinstance(user.get("profile"), dict)
        else {}
    )

    username = str(
        user.get("username", "")
    ).strip()

    if not username:
        raise ValueError("username is required")

    payload = {
        "username": username,
        "password": str(
            user.get("password", "")
        ),
        "created_at": str(
            user.get("created_at")
            or datetime.now(timezone.utc).isoformat()
        ),
        "display_name": str(
            profile.get("display_name")
            or username
        ),
        "status": str(
            profile.get("status")
            or "سلام، من در گپینو هستم"
        ),
        "avatar": str(
            profile.get("avatar")
            or ""
        ),
    }

    init_database()

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
            ON CONFLICT (username)
            DO UPDATE SET
                password = EXCLUDED.password,
                created_at = EXCLUDED.created_at,
                display_name = EXCLUDED.display_name,
                status = EXCLUDED.status,
                avatar = EXCLUDED.avatar
            RETURNING
                username,
                password,
                created_at,
                display_name,
                status,
                avatar
            """,
            payload,
        ).fetchone()

    return _user_from_row(row)


def db_update_user(
    username: str,
    *,
    status: Optional[str] = None,
    profile: Optional[dict] = None,
) -> Optional[dict]:

    current = db_get_user(username)

    if not current:
        return None

    if profile is not None:
        current["profile"] = profile

    if status is not None:
        current["profile"]["status"] = status

    return db_upsert_user(current)


def db_get_messages(
    user1: Optional[str] = None,
    user2: Optional[str] = None,
) -> list[dict]:

    init_database()

    with get_conn() as conn:
        if user1 is not None and user2 is not None:
            rows = conn.execute(
                """
                SELECT
                    id,
                    sender,
                    receiver,
                    text,
                    created_at
                FROM public.messages
                WHERE
                    (sender = %s AND receiver = %s)
                    OR
                    (sender = %s AND receiver = %s)
                ORDER BY created_at ASC
                """,
                (
                    user1,
                    user2,
                    user2,
                    user1,
                ),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT
                    id,
                    sender,
                    receiver,
                    text,
                    created_at
                FROM public.messages
                ORDER BY created_at ASC
                """
            ).fetchall()

    return [
        dict(row)
        for row in rows
        if row
    ]


def db_insert_message(message: dict) -> dict:
    init_database()

    payload = {
        "id": str(message["id"]),
        "sender": str(message["sender"]),
        "receiver": str(message["receiver"]),
        "text": str(message["text"]),
        "created_at": str(message["created_at"]),
    }

    with get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO public.messages
            (
                id,
                sender,
                receiver,
                text,
                created_at
            )
            VALUES
            (
                %(id)s,
                %(sender)s,
                %(receiver)s,
                %(text)s,
                %(created_at)s
            )
            ON CONFLICT (id)
            DO NOTHING
            RETURNING
                id,
                sender,
                receiver,
                text,
                created_at
            """,
            payload,
        ).fetchone()

    return dict(row) if row else payload


def migrate_json_to_database(
    users_file: Path,
    messages_file: Path,
) -> None:

    if not DATABASE_ENABLED:
        return

    # اول ساخت/تکمیل ساختار DB
    init_database()

    def read_json(path: Path, default):
        try:
            with path.open(
                "r",
                encoding="utf-8",
            ) as f:
                value = json.load(f)

            return (
                value
                if isinstance(value, type(default))
                else default
            )

        except (
            OSError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ):
            return default

    users = read_json(
        users_file,
        [],
    )

    messages = read_json(
        messages_file,
        [],
    )

    if users:
        for user in users:
            if (
                isinstance(user, dict)
                and user.get("username")
            ):
                db_upsert_user(user)

    if messages:
        for message in messages:
            if not isinstance(message, dict):
                continue

            if all(
                message.get(key)
                for key in (
                    "id",
                    "sender",
                    "receiver",
                    "text",
                    "created_at",
                )
            ):
                db_insert_message(message)