# db.py - GAPINO DATABASE
# PostgreSQL + Chat + Files + Live Streaming

import json
import os
import secrets
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Iterator, Optional


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    ""
).strip()


DATABASE_ENABLED = bool(DATABASE_URL)


def _normalize_db_url(url: str):

    if url.startswith("postgres://"):

        return "postgresql://" + url[len("postgres://"):]

    return url



if DATABASE_ENABLED:

    DATABASE_URL = _normalize_db_url(
        DATABASE_URL
    )



@contextmanager
def get_conn() -> Iterator[object]:

    if not DATABASE_ENABLED:

        raise RuntimeError(
            "DATABASE_URL not configured"
        )


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





# ==============================
# DATABASE INIT
# ==============================


def init_database():

    if not DATABASE_ENABLED:

        return


    with get_conn() as conn:


        # USERS

        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (

            username TEXT PRIMARY KEY,

            password TEXT NOT NULL,

            created_at TEXT NOT NULL,

            display_name TEXT DEFAULT '',

            status TEXT DEFAULT '',

            avatar TEXT DEFAULT ''

        )
        """)



        # MESSAGES


        conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (

            id TEXT PRIMARY KEY,

            sender TEXT NOT NULL,

            receiver TEXT NOT NULL,

            text TEXT DEFAULT '',

            created_at TEXT NOT NULL,

            file_id TEXT,

            file_name TEXT,

            file_type TEXT,

            file_url TEXT,

            file_size BIGINT

        )
        """)




        # FILES


        conn.execute("""
        CREATE TABLE IF NOT EXISTS file_blobs (

            id TEXT PRIMARY KEY,

            owner TEXT NOT NULL,

            kind TEXT NOT NULL,

            original_name TEXT NOT NULL,

            content_type TEXT NOT NULL,

            size_bytes BIGINT,

            data BYTEA NOT NULL,

            created_at TIMESTAMP DEFAULT NOW()

        )
        """)



        # LIVE STREAM


        conn.execute("""
        CREATE TABLE IF NOT EXISTS live_streams (

            id TEXT PRIMARY KEY,

            owner TEXT NOT NULL,

            title TEXT NOT NULL,

            description TEXT DEFAULT '',

            status TEXT DEFAULT 'created',

            viewers INTEGER DEFAULT 0,

            created_at TEXT NOT NULL,

            started_at TEXT DEFAULT '',

            ended_at TEXT DEFAULT ''

        )
        """)



        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_live_status
        ON live_streams(status)
        """)






# ==============================
# USERS
# ==============================


def db_get_user(username):

    with get_conn() as conn:

        row = conn.execute(
            """
            SELECT *
            FROM users
            WHERE username=%s
            """,
            (username,)
        ).fetchone()


    return dict(row) if row else None





def db_list_users():

    with get_conn() as conn:

        rows = conn.execute(
            """
            SELECT *
            FROM users
            ORDER BY created_at
            """
        ).fetchall()


    return [
        dict(x)
        for x in rows
    ]





def db_upsert_user(user):

    profile = user.get(
        "profile",
        {}
    )


    with get_conn() as conn:

        conn.execute(
        """
        INSERT INTO users
        (
        username,
        password,
        created_at,
        display_name,
        status,
        avatar
        )

        VALUES
        (%s,%s,%s,%s,%s,%s)


        ON CONFLICT(username)
        DO UPDATE SET

        password=excluded.password,

        display_name=excluded.display_name,

        status=excluded.status,

        avatar=excluded.avatar

        """,
        (

        user["username"],

        user["password"],

        user["created_at"],

        profile.get(
            "display_name",
            ""
        ),

        profile.get(
            "status",
            ""
        ),

        profile.get(
            "avatar",
            ""
        )

        ))




    return user
# ==============================
# MESSAGES
# ==============================


def db_get_messages(
    user1=None,
    user2=None
):

    with get_conn() as conn:

        if user1 and user2:

            rows = conn.execute(
                """
                SELECT *
                FROM messages

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
                FROM messages
                ORDER BY created_at ASC
                """
            ).fetchall()


    return [
        dict(row)
        for row in rows
    ]





def db_insert_message(message):

    with get_conn() as conn:

        conn.execute(
        """
        INSERT INTO messages

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

        (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)

        ON CONFLICT(id)
        DO NOTHING

        """,

        (

        message["id"],

        message["sender"],

        message["receiver"],

        message.get(
            "text",
            ""
        ),

        message["created_at"],

        message.get(
            "file_id"
        ),

        message.get(
            "file_name"
        ),

        message.get(
            "file_type"
        ),

        message.get(
            "file_url"
        ),

        message.get(
            "file_size"
        )

        ))


    return message






# ==============================
# FILE STORAGE
# ==============================


def db_store_file(
    owner,
    kind,
    original_name,
    content_type,
    data
):

    file_id = secrets.token_hex(20)


    with get_conn() as conn:

        conn.execute(
        """
        INSERT INTO file_blobs

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
        (%s,%s,%s,%s,%s,%s,%s)

        """,

        (

        file_id,

        owner,

        kind,

        original_name,

        content_type,

        len(data),

        data

        ))


    return file_id





def db_get_file(file_id):

    with get_conn() as conn:

        row = conn.execute(
        """
        SELECT *
        FROM file_blobs

        WHERE id=%s
        """,
        (file_id,)
        ).fetchone()


    return dict(row) if row else None





def db_delete_file(file_id):

    with get_conn() as conn:

        conn.execute(
        """
        DELETE FROM file_blobs

        WHERE id=%s
        """,
        (file_id,)
        )






# ==============================
# GAPINO LIVE STREAM
# ==============================


def db_create_live(
    owner,
    title,
    description=""
):

    live_id = secrets.token_hex(12)


    now = datetime.now(
        timezone.utc
    ).isoformat()



    with get_conn() as conn:

        conn.execute(
        """
        INSERT INTO live_streams

        (
        id,
        owner,
        title,
        description,
        status,
        created_at
        )

        VALUES

        (%s,%s,%s,%s,%s,%s)

        """,

        (

        live_id,

        owner,

        title,

        description,

        "created",

        now

        ))



    return {

        "id": live_id,

        "owner": owner,

        "title": title,

        "status": "created"

    }







def db_start_live(
    live_id
):

    now = datetime.now(
        timezone.utc
    ).isoformat()


    with get_conn() as conn:

        conn.execute(
        """
        UPDATE live_streams

        SET

        status='live',

        started_at=%s

        WHERE id=%s

        """,

        (
            now,
            live_id
        ))


    return True






def db_stop_live(
    live_id
):

    now = datetime.now(
        timezone.utc
    ).isoformat()


    with get_conn() as conn:

        conn.execute(
        """
        UPDATE live_streams

        SET

        status='ended',

        ended_at=%s

        WHERE id=%s

        """,

        (
            now,
            live_id
        ))


    return True






def db_get_live(
    live_id
):

    with get_conn() as conn:

        row = conn.execute(
        """
        SELECT *

        FROM live_streams

        WHERE id=%s

        """,

        (
            live_id,
        )

        ).fetchone()


    return dict(row) if row else None






def db_list_live():

    with get_conn() as conn:

        rows = conn.execute(
        """
        SELECT *

        FROM live_streams

        WHERE status='live'

        ORDER BY created_at DESC

        """
        ).fetchall()


    return [
        dict(row)
        for row in rows
    ]







# ==============================
# JSON MIGRATION
# ==============================


def migrate_json_to_database(
    users_file: Path,
    messages_file: Path
):

    if not DATABASE_ENABLED:

        return



    try:

        with users_file.open(
            "r",
            encoding="utf-8"
        ) as f:

            users = json.load(f)


    except Exception:

        users = []



    for user in users:

        if isinstance(user, dict):

            if user.get("username"):

                db_upsert_user(
                    user
                )




    try:

        with messages_file.open(
            "r",
            encoding="utf-8"
        ) as f:

            messages=json.load(f)


    except Exception:

        messages=[]




    for msg in messages:

        if isinstance(msg,dict):

            if msg.get("id"):

                db_insert_message(
                    msg
                )