# ===============================
# GAPINO WEB - MAIN.PY PART 1/4
# ===============================

from fastapi import (
    FastAPI,
    Request,
    Form,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    UploadFile,
    File,
)

from fastapi.responses import (
    HTMLResponse,
    FileResponse,
)

from starlette.middleware.sessions import SessionMiddleware

from pathlib import Path
from datetime import datetime
import hashlib
import hmac
import json
import os
import secrets
import threading

app = FastAPI(
    title="GAPINO Web",
    version="1.0"
)

from db import (
    DATABASE_ENABLED,
    init_database,
    migrate_json_to_database,

    db_get_user,
    db_list_users,
    db_upsert_user,
    db_update_user,

    db_get_messages,
    db_insert_message,

    # LIVE
    db_create_live,
    db_start_live,
    db_stop_live,
    db_get_live,
    db_get_active_lives,
)


# ===============================
# APP SETTINGS
# ===============================


APP_NAME = "گپینو"


BASE_DIR = Path(__file__).resolve().parent


DATA_DIR = BASE_DIR / "data"

AVATARS_DIR = DATA_DIR / "avatars"


USERS_FILE = DATA_DIR / "users.json"

MESSAGES_FILE = DATA_DIR / "messages.json"



DATA_DIR.mkdir(
    parents=True,
    exist_ok=True
)


AVATARS_DIR.mkdir(
    parents=True,
    exist_ok=True
)



SESSION_SECRET = os.getenv(
    "GAPINO_SESSION_SECRET",
    "change-this-secret-before-production"
)



MAX_AVATAR_SIZE = 5 * 1024 * 1024



ALLOWED_AVATAR_TYPES = {

    "image/jpeg": ".jpg",

    "image/png": ".png",

    "image/gif": ".gif",

    "image/webp": ".webp",
}



# ===============================
# FASTAPI APP
# ===============================


app = FastAPI(
    title=APP_NAME
)



app.add_middleware(
    SessionMiddleware,

    secret_key=SESSION_SECRET,

    session_cookie="gapino_session",

    max_age=60 * 60 * 24 * 30,

    same_site="lax",

    https_only=False,
)



# ===============================
# LOCKS
# ===============================


file_lock = threading.Lock()


connections = {}


connections_lock = threading.Lock()



# ===============================
# JSON HELPERS
# ===============================


def save_json(
    path: Path,
    data
):

    temp = path.with_suffix(
        path.suffix + ".tmp"
    )


    with temp.open(
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


    temp.replace(path)




def load_json(
    path: Path,
    default
):

    if not path.exists():

        save_json(
            path,
            default
        )

        return default


    try:

        with path.open(
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)


    except Exception:

        return default



# ===============================
# DATA LOADERS
# ===============================


def load_users():

    if DATABASE_ENABLED:

        return db_list_users()


    data = load_json(
        USERS_FILE,
        []
    )


    return (
        data
        if isinstance(data, list)
        else []
    )





def load_messages():

    if DATABASE_ENABLED:

        return db_get_messages()


    data = load_json(
        MESSAGES_FILE,
        []
    )


    return (
        data
        if isinstance(data, list)
        else []
    )





def now_text():

    return datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )



# ===============================
# PASSWORD
# ===============================


def hash_password(
    password: str
):

    salt = secrets.token_bytes(16)


    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt,
        200000
    )


    return (
        "$pbkdf2$"
        + salt.hex()
        + "$"
        + digest.hex()
    )





def verify_password(
    password: str,
    stored: str
):

    try:

        parts = stored.split("$")


        if len(parts) != 4:
            return False


        if parts[1] != "pbkdf2":
            return False


        salt = bytes.fromhex(
            parts[2]
        )


        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            salt,
            200000
        )


        return hmac.compare_digest(
            digest.hex(),
            parts[3]
        )


    except Exception:

        return False



# ===============================
# PROFILE HELPERS
# ===============================


def ensure_profile(
    user: dict
):

    profile = user.get(
        "profile"
    )


    if not isinstance(
        profile,
        dict
    ):

        profile = {}


    profile.setdefault(
        "display_name",
        user.get(
            "username",
            ""
        )
    )


    profile.setdefault(
        "status",
        "سلام، من در گپینو هستم"
    )


    profile.setdefault(
        "avatar",
        ""
    )


    user["profile"] = profile


    return user
# ===============================
# USER HELPERS
# ===============================


def public_profile(user: dict):

    ensure_profile(user)

    return {
        "display_name": user["profile"].get(
            "display_name",
            user.get("username", "")
        ),

        "status": user["profile"].get(
            "status",
            ""
        ),

        "avatar": user["profile"].get(
            "avatar",
            ""
        ),
    }




def public_user(user: dict):

    ensure_profile(user)

    return {

        "username": user.get(
            "username",
            ""
        ),

        "created_at": user.get(
            "created_at",
            ""
        ),

        "profile": public_profile(user)

    }





def get_current_user(
    request: Request
):

    username = request.session.get(
        "username"
    )


    if not username:
        return None



    if DATABASE_ENABLED:

        user = db_get_user(
            username
        )

        return (
            ensure_profile(user)
            if user
            else None
        )



    for user in load_users():

        if user.get(
            "username"
        ) == username:

            return ensure_profile(
                user
            )


    return None





def find_user(
    username: str
):

    if DATABASE_ENABLED:

        user = db_get_user(
            username
        )

        return (
            ensure_profile(user)
            if user
            else None
        )



    for user in load_users():

        if user.get(
            "username"
        ) == username:

            return user


    return None





def get_private_messages(
    user1: str,
    user2: str
):

    if DATABASE_ENABLED:

        return db_get_messages(
            user1,
            user2
        )



    result = []


    for message in load_messages():

        if (
            message.get("sender") == user1
            and
            message.get("receiver") == user2
        ) or (
            message.get("sender") == user2
            and
            message.get("receiver") == user1
        ):

            result.append(message)



    return result





# ===============================
# START DATABASE
# ===============================


if not USERS_FILE.exists():

    save_json(
        USERS_FILE,
        []
    )


if not MESSAGES_FILE.exists():

    save_json(
        MESSAGES_FILE,
        []
    )



if DATABASE_ENABLED:

    init_database()

    migrate_json_to_database(
        USERS_FILE,
        MESSAGES_FILE
    )



# ===============================
# AUTH API
# ===============================


@app.get("/health")
async def health():

    return {

        "status": "ok",

        "app": APP_NAME,

        "time": now_text()

    }





@app.get("/me")
async def me_endpoint(
    request: Request
):

    user = get_current_user(
        request
    )


    return {

        "authenticated": bool(user),

        "user":
            public_user(user)
            if user
            else None

    }





@app.post("/register")
async def register(
    username: str = Form(...),
    password: str = Form(...)
):

    username = username.strip()


    if len(username) < 3:

        raise HTTPException(
            400,
            "نام کاربری کوتاه است."
        )



    if len(password) < 4:

        raise HTTPException(
            400,
            "رمز عبور کوتاه است."
        )



    with file_lock:


        users = load_users()



        if any(
            u.get("username") == username
            for u in users
        ):

            raise HTTPException(
                400,
                "این کاربر وجود دارد."
            )



        new_user = {

            "username": username,

            "password": hash_password(
                password
            ),

            "created_at": now_text(),

            "profile": {

                "display_name": username,

                "status":
                    "سلام، من در گپینو هستم",

                "avatar": ""

            }

        }



        if DATABASE_ENABLED:

            db_upsert_user(
                new_user
            )

        else:

            users.append(
                new_user
            )

            save_json(
                USERS_FILE,
                users
            )



    return {

        "ok": True

    }





@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):

    username = username.strip()


    for user in load_users():

        if user.get(
            "username"
        ) == username:


            if verify_password(
                password,
                user.get(
                    "password",
                    ""
                )
            ):

                request.session[
                    "username"
                ] = username


                return {

                    "ok": True,

                    "user":
                        public_user(user)

                }



    raise HTTPException(
        401,
        "نام کاربری یا رمز اشتباه است."
    )





@app.post("/logout")
async def logout(
    request: Request
):

    request.session.clear()


    return {

        "ok": True

    }
# ===============================
# PROFILE API
# ===============================


@app.get("/profile")
async def get_profile(
    request: Request
):

    user = get_current_user(request)

    if not user:
        raise HTTPException(
            401,
            "ابتدا وارد شوید."
        )


    return {
        "profile": public_profile(user),
        "user": public_user(user)
    }





@app.put("/profile")
async def update_profile(
    request: Request
):

    user = get_current_user(request)

    if not user:
        raise HTTPException(
            401,
            "ابتدا وارد شوید."
        )


    data = await request.json()


    display_name = str(
        data.get("display_name","")
    ).strip()


    status = str(
        data.get("status","")
    ).strip()



    if not display_name:
        raise HTTPException(
            400,
            "نام نمایشی خالی است."
        )



    with file_lock:

        users = load_users()


        target = next(
            (
                u for u in users
                if u.get("username")
                ==
                user.get("username")
            ),
            None
        )


        if not target:
            raise HTTPException(
                404,
                "کاربر پیدا نشد."
            )



        ensure_profile(target)


        target["profile"] = {

            "display_name": display_name,

            "status": status,

            "avatar":
                target["profile"].get(
                    "avatar",
                    ""
                )

        }



        if DATABASE_ENABLED:

            db_upsert_user(
                target
            )

        else:

            save_json(
                USERS_FILE,
                users
            )



    return {

        "ok": True,

        "user":
            public_user(target)

    }





# ===============================
# USERS API
# ===============================


@app.get("/users")
async def users_api(
    request: Request
):

    current = get_current_user(
        request
    )

    if not current:

        raise HTTPException(
            401,
            "ابتدا وارد شوید."
        )



    result=[]


    for user in load_users():

        if user.get(
            "username"
        ) != current.get(
            "username"
        ):

            result.append(
                public_user(user)
            )


    return {

        "users": result

    }





# ===============================
# MESSAGE API
# ===============================


async def store_message(
    sender,
    receiver,
    text
):

    message = {

        "id":
            secrets.token_hex(12),

        "sender":
            sender,

        "receiver":
            receiver,

        "text":
            text,

        "created_at":
            now_text()

    }



    if DATABASE_ENABLED:

        db_insert_message(
            message
        )

    else:

        messages = load_messages()

        messages.append(
            message
        )

        save_json(
            MESSAGES_FILE,
            messages[-10000:]
        )


    return message





@app.get("/messages/{username}")
async def messages_api(
    request: Request,
    username: str
):

    user = get_current_user(
        request
    )


    if not user:

        raise HTTPException(
            401,
            "ابتدا وارد شوید."
        )


    return {

        "messages":
            get_private_messages(
                user["username"],
                username
            )

    }





@app.post("/messages")
async def send_message(
    request: Request
):

    user = get_current_user(
        request
    )


    if not user:

        raise HTTPException(
            401,
            "ابتدا وارد شوید."
        )



    data = await request.json()


    receiver = str(
        data.get("receiver","")
    ).strip()


    text = str(
        data.get("text","")
    ).strip()



    if not receiver or not text:

        raise HTTPException(
            400,
            "اطلاعات ناقص است."
        )



    message = await store_message(
        user["username"],
        receiver,
        text
    )


    return {

        "ok": True,

        "message": message

    }





# ===============================
# LIVE STREAM API
# ===============================


@app.post("/live/create")
async def create_live(
    request: Request
):

    user = get_current_user(
        request
    )


    if not user:

        raise HTTPException(
            401,
            "ابتدا وارد شوید."
        )


    data = await request.json()


    title = str(
        data.get("title","")
    ).strip()


    description = str(
        data.get("description","")
    ).strip()



    if not title:

        raise HTTPException(
            400,
            "عنوان لایو لازم است."
        )



    live = db_create_live(
        user["username"],
        title,
        description
    )



    return {

        "ok": True,

        "live": live

    }





@app.post("/live/{live_id}/start")
async def start_live(
    request: Request,
    live_id: str
):

    user = get_current_user(
        request
    )


    if not user:

        raise HTTPException(
            401,
            "ابتدا وارد شوید."
        )



    live = db_start_live(
        live_id,
        user["username"]
    )


    if not live:

        raise HTTPException(
            404,
            "لایو پیدا نشد."
        )



    return {

        "ok": True,

        "live": live

    }





@app.post("/live/{live_id}/stop")
async def stop_live(
    request: Request,
    live_id: str
):

    user = get_current_user(
        request
    )


    live = db_stop_live(
        live_id,
        user["username"]
    )


    if not live:

        raise HTTPException(
            404,
            "لایو پیدا نشد."
        )



    return {

        "ok": True,

        "live": live

    }





@app.get("/live/list")
async def live_list():

    return {

        "lives":
            db_get_active_lives()

    }





@app.get("/live/{live_id}")
async def live_info(
    live_id: str
):

    live = db_get_live(
        live_id
    )


    if not live:

        raise HTTPException(
            404,
            "لایو پیدا نشد."
        )


    return {

        "live": live

    }
# ===============================
# WEBSOCKET
# ===============================


async def send_to_user(
    username,
    payload
):

    with connections_lock:

        sockets = list(
            connections.get(
                username,
                set()
            )
        )


    for ws in sockets:

        try:

            await ws.send_json(
                payload
            )

        except Exception:

            pass





async def broadcast_online():

    with connections_lock:

        sockets = [
            ws
            for group in connections.values()
            for ws in group
        ]


        users = list(
            connections.keys()
        )



    data = {

        "type":
            "online_users",

        "users":
            users

    }



    for ws in sockets:

        try:

            await ws.send_json(
                data
            )

        except Exception:

            pass





@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket
):

    await websocket.accept()



    username = (
        websocket.session.get(
            "username"
        )
        if hasattr(
            websocket,
            "session"
        )
        else None
    )



    if not username:

        await websocket.send_json({

            "type":"error",

            "message":
                "ابتدا وارد شوید."

        })


        await websocket.close()

        return



    with connections_lock:

        connections.setdefault(
            username,
            set()
        ).add(
            websocket
        )



    await broadcast_online()



    try:

        while True:


            data = await websocket.receive_json()


            kind = data.get(
                "type"
            )



            # پیام

            if kind == "message":


                target = str(
                    data.get(
                        "to",
                        ""
                    )
                ).strip()



                text = str(
                    data.get(
                        "text",
                        ""
                    )
                ).strip()



                if not target or not text:

                    continue



                message = await store_message(

                    username,

                    target,

                    text

                )



                payload = {

                    "type":
                        "message",

                    "message":
                        message

                }



                await send_to_user(

                    target,

                    payload

                )


                await send_to_user(

                    username,

                    payload

                )




            # در حال نوشتن

            elif kind == "typing":


                target = str(
                    data.get(
                        "to",
                        ""
                    )
                )


                await send_to_user(

                    target,

                    {

                        "type":
                            "typing",

                        "from":
                            username,

                        "value":
                            bool(
                                data.get(
                                    "value"
                                )
                            )

                    }

                )



    except WebSocketDisconnect:

        pass



    except Exception as e:

        print(
            "WebSocket Error:",
            e
        )



    finally:


        with connections_lock:


            group = connections.get(
                username
            )


            if group:

                group.discard(
                    websocket
                )


                if not group:

                    connections.pop(
                        username,
                        None
                    )



        await broadcast_online()





# ===============================
# START SERVER
# ===============================


if __name__ == "__main__":


    import uvicorn


    port = int(
        os.getenv(
            "PORT",
            "8000"
        )
    )


    uvicorn.run(

        app,

        host="0.0.0.0",

        port=port

    )