from fastapi import FastAPI, Request, Form, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path
from datetime import datetime
import hashlib
import hmac
import json
import os
import secrets
import threading

APP_NAME = "گپینو"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
AVATARS_DIR = DATA_DIR / "avatars"
USERS_FILE = DATA_DIR / "users.json"
MESSAGES_FILE = DATA_DIR / "messages.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
AVATARS_DIR.mkdir(parents=True, exist_ok=True)

SESSION_SECRET = os.getenv("GAPINO_SESSION_SECRET", "change-this-secret-before-production")
MAX_AVATAR_SIZE = 5 * 1024 * 1024
ALLOWED_AVATAR_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

app = FastAPI(title=APP_NAME)

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="gapino_session",
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=False,
)

file_lock = threading.Lock()
connections = {}
connections_lock = threading.Lock()


def save_json(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def load_json(path: Path, default):
    if not path.exists():
        save_json(path, default)
        return default

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def load_users():
    data = load_json(USERS_FILE, [])
    return data if isinstance(data, list) else []


def load_messages():
    data = load_json(MESSAGES_FILE, [])
    return data if isinstance(data, list) else []


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        200_000,
    )
    return f"$pbkdf2${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        parts = stored.split("$")

        if len(parts) != 4 or parts[1] != "pbkdf2":
            return False

        salt = bytes.fromhex(parts[2])
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            200_000,
        )

        return hmac.compare_digest(digest.hex(), parts[3])

    except (ValueError, TypeError):
        return False


def ensure_profile(user: dict) -> dict:
    profile = user.get("profile")

    if not isinstance(profile, dict):
        profile = {}

    profile.setdefault(
        "display_name",
        user.get("username", ""),
    )

    profile.setdefault(
        "status",
        "سلام، من در گپینو هستم",
    )

    profile.setdefault(
        "avatar",
        "",
    )

    user["profile"] = profile
    return user


def public_profile(user: dict) -> dict:
    ensure_profile(user)

    profile = user["profile"]

    return {
        "display_name": profile.get(
            "display_name",
            user.get("username", ""),
        ),
        "status": profile.get(
            "status",
            "",
        ),
        "avatar": profile.get(
            "avatar",
            "",
        ),
    }


def public_user(user: dict) -> dict:
    ensure_profile(user)

    return {
        "username": user.get(
            "username",
            "",
        ),
        "created_at": user.get(
            "created_at",
            "",
        ),
        "profile": public_profile(user),
    }


def get_current_user(request: Request):
    username = request.session.get("username")

    if not username:
        return None

    for user in load_users():
        if user.get("username") == username:
            return ensure_profile(user)

    return None


def find_user(username: str):
    for user in load_users():
        if user.get("username") == username:
            return user

    return None


def delete_avatar_file(avatar_url: str):
    if not avatar_url:
        return

    if not avatar_url.startswith("/avatars/"):
        return

    filename = Path(
        avatar_url[len("/avatars/"):]
    ).name

    if not filename:
        return

    path = AVATARS_DIR / filename

    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def get_private_messages(user1: str, user2: str):
    result = []

    for message in load_messages():
        sender = message.get("sender")
        receiver = message.get("receiver")

        if (
            (sender == user1 and receiver == user2)
            or
            (sender == user2 and receiver == user1)
        ):
            result.append(message)

    return result


if not USERS_FILE.exists():
    save_json(USERS_FILE, [])


if not MESSAGES_FILE.exists():
    save_json(MESSAGES_FILE, [])


HTML = r'''<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<meta
    name="theme-color"
    content="#2563eb"
>

<title>گپینو</title>

<style>

*{
    box-sizing:border-box
}

html,
body{
    width:100%;
    height:100%;
    margin:0
}

body{
    font-family:Tahoma,Arial,sans-serif;
    background:#0e141b;
    color:#fff;
    direction:rtl
}

button,
input,
textarea{
    font-family:inherit
}

button{
    cursor:pointer
}

.hidden{
    display:none!important
}

.auth{
    min-height:100vh;
    display:flex;
    align-items:center;
    justify-content:center;
    padding:20px;
    background:
        radial-gradient(
            circle at top,
            #1b3158,
            #0e141b 60%
        )
}

.card{
    width:100%;
    max-width:420px;
    background:#171f29;
    border:1px solid #2d3947;
    border-radius:22px;
    padding:28px;
    box-shadow:
        0 25px 70px rgba(0,0,0,.45)
}

.logo{
    text-align:center;
    font-size:38px;
    font-weight:900
}

.sub{
    text-align:center;
    color:#9aa7b7;
    margin:8px 0 24px
}

.card input{
    width:100%;
    margin-bottom:12px;
    padding:13px 14px;
    border-radius:12px;
    border:1px solid #354253;
    background:#0d131a;
    color:#fff;
    outline:none
}

.card input:focus{
    border-color:#3b82f6
}

.btn{
    width:100%;
    padding:13px;
    border-radius:12px;
    font-weight:800;
    font-size:15px
}

.primary{
    background:#2563eb;
    color:#fff;
    border:0
}

.secondary{
    margin-top:10px;
    background:transparent;
    color:#fff;
    border:1px solid #394556
}

.error{
    text-align:center;
    min-height:22px;
    margin-top:10px;
    color:#ff7f92;
    font-size:13px
}

.app{
    height:100vh;
    display:flex;
    overflow:hidden
}

.sidebar{
    width:340px;
    flex:none;
    background:#151d26;
    border-left:1px solid #2a3542;
    display:flex;
    flex-direction:column
}

.side-head{
    padding:18px;
    border-bottom:1px solid #2a3542
}

.side-logo{
    font-size:26px;
    font-weight:900
}

.me{
    font-size:13px;
    color:#8f9bab;
    margin-top:4px
}

.search{
    width:100%;
    margin-top:14px;
    padding:11px 12px;
    border-radius:11px;
    border:1px solid #344151;
    background:#0d131a;
    color:#fff;
    outline:none
}

.side-buttons{
    display:flex;
    gap:8px;
    margin-top:10px
}

.side-action{
    flex:1;
    padding:10px;
    border-radius:10px;
    border:1px solid #394657;
    background:transparent;
    color:#fff
}

.side-action:hover,
.logout:hover{
    background:#202936
}

.logout{
    margin-top:8px;
    width:100%;
    padding:10px;
    border-radius:10px;
    border:1px solid #394657;
    background:transparent;
    color:#fff
}

.users{
    flex:1;
    overflow:auto
}

.user{
    display:flex;
    gap:12px;
    align-items:center;
    padding:13px 15px;
    border-bottom:1px solid rgba(255,255,255,.03);
    cursor:pointer
}

.user:hover,
.user.active{
    background:#202b38
}

.avatar{
    width:46px;
    height:46px;
    min-width:46px;
    border-radius:50%;
    display:flex;
    align-items:center;
    justify-content:center;
    background:#2563eb;
    font-weight:900;
    overflow:hidden
}

.avatar img{
    width:100%;
    height:100%;
    object-fit:cover
}

.uinfo{
    min-width:0;
    flex:1
}

.uname{
    font-weight:700;
    white-space:nowrap;
    overflow:hidden;
    text-overflow:ellipsis
}

.ustatus{
    font-size:12px;
    color:#788596;
    margin-top:4px;
    white-space:nowrap;
    overflow:hidden;
    text-overflow:ellipsis
}

.ustatus.online{
    color:#50d58e
}

.chat{
    min-width:0;
    flex:1;
    height:100vh;
    display:flex;
    flex-direction:column
}

.chat-head{
    height:70px;
    min-height:70px;
    display:flex;
    align-items:center;
    padding:0 18px;
    background:#151d26;
    border-bottom:1px solid #2a3542
}

.menu{
    display:none;
    margin-left:8px;
    border:0;
    background:transparent;
    color:#fff;
    font-size:22px
}

.chat-name{
    font-size:18px;
    font-weight:800
}

.chat-status{
    font-size:12px;
    color:#7f8b9b;
    margin-top:3px
}

.messages{
    flex:1;
    overflow:auto;
    padding:20px;
    display:flex;
    flex-direction:column;
    gap:9px
}

.empty{
    height:100%;
    display:flex;
    align-items:center;
    justify-content:center;
    color:#728091;
    text-align:center
}

.msg{
    max-width:min(75%,650px);
    padding:9px 12px;
    border-radius:15px;
    line-height:1.8;
    font-size:14px;
    word-break:break-word
}

.mine{
    align-self:flex-start;
    background:#2563eb;
    border-bottom-left-radius:5px
}

.theirs{
    align-self:flex-end;
    background:#222d39;
    border-bottom-right-radius:5px
}

.time{
    display:block;
    font-size:9px;
    opacity:.65;
    margin-top:3px
}

.typing{
    min-height:24px;
    padding:0 18px;
    color:#788697;
    font-size:12px
}

.composer{
    display:flex;
    gap:9px;
    padding:12px;
    border-top:1px solid #2a3542;
    background:#151d26
}

.message-input{
    flex:1;
    min-width:0;
    padding:12px 13px;
    border-radius:12px;
    border:1px solid #364253;
    background:#0d131a;
    color:#fff;
    outline:none
}

.send{
    width:52px;
    border:0;
    border-radius:12px;
    background:#2563eb;
    color:#fff;
    font-size:18px
}

.modal-backdrop{
    position:fixed;
    inset:0;
    z-index:100;
    display:flex;
    align-items:center;
    justify-content:center;
    padding:18px;
    background:rgba(0,0,0,.68)
}

.modal{
    width:100%;
    max-width:460px;
    max-height:92vh;
    overflow:auto;
    background:#171f29;
    border:1px solid #324051;
    border-radius:20px;
    padding:22px;
    box-shadow:
        0 25px 70px rgba(0,0,0,.5)
}

.modal h2{
    margin:0 0 18px
}

.modal label{
    display:block;
    margin:12px 0 6px;
    color:#a8b3c2;
    font-size:13px
}

.modal input,
.modal textarea{
    width:100%;
    padding:12px;
    border-radius:11px;
    border:1px solid #354253;
    background:#0d131a;
    color:#fff;
    outline:none
}

.modal textarea{
    min-height:90px;
    resize:vertical
}

.modal-actions{
    display:flex;
    gap:8px;
    margin-top:16px
}

.modal-actions button{
    flex:1;
    padding:12px;
    border-radius:11px
}

.avatar-preview{
    width:100px;
    height:100px;
    margin:0 auto 12px;
    border-radius:50%;
    display:flex;
    align-items:center;
    justify-content:center;
    background:#2563eb;
    font-size:32px;
    font-weight:900;
    overflow:hidden
}

.avatar-preview img{
    width:100%;
    height:100%;
    object-fit:cover
}

.profile-hint{
    color:#7f8c9c;
    font-size:11px;
    line-height:1.6;
    text-align:center;
    margin-bottom:10px
}

.file-button{
    width:100%;
    display:flex;
    align-items:center;
    justify-content:center;
    padding:12px;
    border-radius:11px;
    background:#202b38;
    border:1px solid #394657;
    color:#fff;
    font-weight:700;
    cursor:pointer
}

.file-button:hover{
    background:#273444
}

.file-name{
    text-align:center;
    color:#8995a5;
    font-size:11px;
    margin-top:7px;
    min-height:18px
}

.remove-avatar{
    width:100%;
    margin-top:8px;
    padding:10px;
    border-radius:10px;
    background:transparent;
    border:1px solid #55343b;
    color:#ff9aaa;
    cursor:pointer
}

.remove-avatar:hover{
    background:#2b1e23
}

@media (max-width:800px){

    .sidebar{
        position:absolute;
        z-index:20;
        top:0;
        right:0;
        bottom:0;
        width:100%;
        max-width:390px
    }

    .sidebar.closed{
        display:none
    }

    .menu{
        display:block
    }

    .msg{
        max-width:88%
    }

    .side-buttons{
        display:grid;
        grid-template-columns:1fr 1fr
    }

}

</style>

</head>

<body>

<div id="auth" class="auth">

    <div class="card">

        <div class="logo">
            گپینو
        </div>

        <div class="sub">
            پیام‌رسان اینترنتی گپینو
        </div>

        <div id="loginBox">

            <input
                id="loginUser"
                placeholder="نام کاربری"
                autocomplete="username"
            >

            <input
                id="loginPass"
                type="password"
                placeholder="رمز عبور"
                autocomplete="current-password"
            >

            <button
                class="btn primary"
                onclick="loginUser()"
            >
                ورود به گپینو
            </button>

            <button
                class="btn secondary"
                onclick="showRegister()"
            >
                ساخت حساب جدید
            </button>

        </div>

        <div
            id="registerBox"
            class="hidden"
        >

            <input
                id="regUser"
                placeholder="نام کاربری"
                autocomplete="username"
            >

            <input
                id="regPass"
                type="password"
                placeholder="رمز عبور"
                autocomplete="new-password"
            >

            <input
                id="regPass2"
                type="password"
                placeholder="تکرار رمز عبور"
                autocomplete="new-password"
            >

            <button
                class="btn primary"
                onclick="registerUser()"
            >
                ساخت حساب
            </button>

            <button
                class="btn secondary"
                onclick="showLogin()"
            >
                بازگشت به ورود
            </button>

        </div>

        <div
            id="error"
            class="error"
        ></div>

    </div>

</div>


<div
    id="app"
    class="app hidden"
>

    <aside
        id="sidebar"
        class="sidebar"
    >

        <div class="side-head">

            <div class="side-logo">
                گپینو
            </div>

            <div
                id="me"
                class="me"
            ></div>

            <input
                id="search"
                class="search"
                placeholder="جستجوی کاربران..."
                oninput="filterUsers()"
            >

            <div class="side-buttons">

                <button
                    class="side-action"
                    onclick="openProfile()"
                >
                    پروفایل من
                </button>

                <button
                    class="side-action"
                    onclick="loadUsers()"
                >
                    به‌روزرسانی
                </button>

            </div>

            <button
                class="logout"
                onclick="logoutUser()"
            >
                خروج از حساب
            </button>

        </div>

        <div
            id="users"
            class="users"
        ></div>

    </aside>


    <main class="chat">

        <div class="chat-head">

            <button
                class="menu"
                onclick="toggleSidebar()"
            >
                ☰
            </button>

            <div>

                <div
                    id="chatName"
                    class="chat-name"
                >
                    گفت‌وگو
                </div>

                <div
                    id="chatStatus"
                    class="chat-status"
                ></div>

            </div>

        </div>


        <div
            id="messages"
            class="messages"
        >

            <div class="empty">
                یک کاربر را از فهرست انتخاب کنید
            </div>

        </div>


        <div
            id="typing"
            class="typing"
        ></div>


        <div class="composer">

            <input
                id="messageInput"
                class="message-input"
                placeholder="پیام خود را بنویسید..."
                oninput="sendTyping()"
                onkeydown="messageKey(event)"
            >

            <button
                class="send"
                onclick="sendMessage()"
            >
                ➤
            </button>

        </div>

    </main>

</div>


<div
    id="profileModal"
    class="modal-backdrop hidden"
>

    <div class="modal">

        <h2>
            پروفایل من
        </h2>

        <div
            id="profileAvatar"
            class="avatar-preview"
        >
            ؟
        </div>

        <div class="profile-hint">
            می‌توانی عکس را از دستگاه خودت انتخاب کنی.
        </div>

        <label>
            عکس پروفایل
        </label>

        <label
            class="file-button"
            for="profileAvatarFile"
        >
            📷 انتخاب عکس
        </label>

        <input
            id="profileAvatarFile"
            type="file"
            accept="image/jpeg,image/png,image/gif,image/webp"
            class="hidden"
            onchange="handleAvatarSelect(event)"
        >

        <div
            id="selectedFileName"
            class="file-name"
        ></div>

        <button
            class="remove-avatar"
            type="button"
            onclick="removeAvatar()"
        >
            حذف عکس پروفایل
        </button>

        <label
            for="profileDisplayName"
        >
            نام نمایشی
        </label>

        <input
            id="profileDisplayName"
            maxlength="50"
            placeholder="مثلاً امیر حسین"
        >

        <label
            for="profileStatus"
        >
            وضعیت
        </label>

        <textarea
            id="profileStatus"
            maxlength="150"
            placeholder="مثلاً در حال کار با گپینو هستم"
        ></textarea>

        <div class="modal-actions">

            <button
                class="primary"
                onclick="saveProfile()"
            >
                ذخیره تغییرات
            </button>

            <button
                class="secondary"
                onclick="closeProfile()"
            >
                انصراف
            </button>

        </div>

        <div
            id="profileError"
            class="error"
        ></div>

    </div>

</div>


<script>

let me = null;
let users = [];
let selected = null;
let socket = null;
let typingTimer = null;
let reconnectTimer = null;
let selectedAvatarFile = null;
let removeAvatarFlag = false;

window.onlineUsers = [];


function err(text){
    document.getElementById("error").textContent = text || "";
}


function profileErr(text){
    document.getElementById("profileError").textContent = text || "";
}


function esc(value){
    return String(value ?? "")
        .replaceAll("&","&amp;")
        .replaceAll("<","&lt;")
        .replaceAll(">","&gt;")
        .replaceAll('"',"&quot;")
        .replaceAll("'","&#039;");
}


function safe(value){
    return String(value)
        .replace(/[^a-zA-Z0-9_-]/g,"_");
}


async function api(url, options = {}){

    const response = await fetch(
        url,
        {
            credentials:"include",
            ...options
        }
    );

    let data = {};

    try{
        data = await response.json();
    }catch(_){}

    if(!response.ok){
        throw new Error(
            data.detail || "خطایی رخ داد."
        );
    }

    return data;
}


function profileOf(user){
    return (user && user.profile) || {};
}


function userLabel(user){

    const p = profileOf(user);

    return p.display_name || user.username;
}


function userStatus(user){

    const p = profileOf(user);

    return p.status || "";
}


function userAvatarHtml(user){

    const p = profileOf(user);

    if(p.avatar){

        return '<img src="' +
            esc(p.avatar) +
            '" alt="">';

    }

    const name =
        userLabel(user) ||
        user.username ||
        "?";

    return esc(
        name.substring(0,1).toUpperCase()
    );
}


function showLogin(){

    document
        .getElementById("loginBox")
        .classList.remove("hidden");

    document
        .getElementById("registerBox")
        .classList.add("hidden");

    err("");
}


function showRegister(){

    document
        .getElementById("loginBox")
        .classList.add("hidden");

    document
        .getElementById("registerBox")
        .classList.remove("hidden");

    err("");
}


async function loginUser(){

    const username =
        document
            .getElementById("loginUser")
            .value
            .trim();

    const password =
        document
            .getElementById("loginPass")
            .value;

    if(!username || !password){

        err(
            "نام کاربری و رمز عبور را وارد کنید."
        );

        return;
    }

    try{

        await api(
            "/login",
            {
                method:"POST",
                headers:{
                    "Content-Type":
                        "application/x-www-form-urlencoded"
                },
                body:new URLSearchParams({
                    username,
                    password
                })
            }
        );

        await startApp();

    }catch(error){

        err(error.message);

    }
}


async function registerUser(){

    const username =
        document
            .getElementById("regUser")
            .value
            .trim();

    const password =
        document
            .getElementById("regPass")
            .value;

    const password2 =
        document
            .getElementById("regPass2")
            .value;

    if(!username || !password || !password2){

        err(
            "همه فیلدها را پر کنید."
        );

        return;
    }

    if(password.length < 4){

        err(
            "رمز عبور حداقل ۴ کاراکتر باشد."
        );

        return;
    }

    if(password !== password2){

        err(
            "تکرار رمز عبور صحیح نیست."
        );

        return;
    }

    try{

        await api(
            "/register",
            {
                method:"POST",
                headers:{
                    "Content-Type":
                        "application/x-www-form-urlencoded"
                },
                body:new URLSearchParams({
                    username,
                    password
                })
            }
        );

        document
            .getElementById("loginUser")
            .value = username;

        document
            .getElementById("loginPass")
            .value = password;

        showLogin();

        err(
            "حساب ساخته شد. اکنون وارد شوید."
        );

    }catch(error){

        err(error.message);

    }
}


async function logoutUser(){

    try{

        await api(
            "/logout",
            {
                method:"POST"
            }
        );

    }catch(_){}

    if(socket){

        try{
            socket.close();
        }catch(_){}

    }

    clearTimeout(reconnectTimer);

    socket = null;
    me = null;
    selected = null;
    users = [];
    window.onlineUsers = [];

    document
        .getElementById("app")
        .classList.add("hidden");

    document
        .getElementById("auth")
        .classList.remove("hidden");
}


async function startApp(){

    const data = await api("/me");

    if(!data.user){
        return;
    }

    me = data.user;

    document
        .getElementById("auth")
        .classList.add("hidden");

    document
        .getElementById("app")
        .classList.remove("hidden");

    renderMe();

    await loadUsers();

    connectSocket();
}


function renderMe(){

    document.getElementById("me").textContent =
        "حساب: " + userLabel(me);

}


async function loadUsers(){

    try{

        const data = await api("/users");

        users = data.users || [];

        renderUsers(
            filterList(users)
        );

    }catch(error){

        console.error(error);

    }
}


function filterList(list){

    const q =
        document
            .getElementById("search")
            .value
            .trim()
            .toLowerCase();

    if(!q){
        return list;
    }

    return list.filter(
        user =>
            (user.username || "")
                .toLowerCase()
                .includes(q)

            ||

            (userLabel(user) || "")
                .toLowerCase()
                .includes(q)
    );
}


function filterUsers(){

    renderUsers(
        filterList(users)
    );

}


function renderUsers(list){

    const box =
        document.getElementById("users");

    box.innerHTML = "";

    if(!list.length){

        box.innerHTML =
            '<div style="padding:20px;text-align:center;color:#788596;">کاربری پیدا نشد</div>';

        return;
    }

    for(const user of list){

        const element =
            document.createElement("div");

        element.className =
            "user" +
            (
                selected &&
                selected.username === user.username
                    ? " active"
                    : ""
            );

        element.innerHTML =
            '<div class="avatar">' +
                userAvatarHtml(user) +
            '</div>' +

            '<div class="uinfo">' +

                '<div class="uname">' +
                    esc(userLabel(user)) +
                '</div>' +

                '<div class="ustatus" id="status-' +
                    safe(user.username) +
                '">' +
                    esc(
                        userStatus(user) ||
                        user.username
                    ) +
                '</div>' +

            '</div>';

        element.onclick =
            () => selectUser(user);

        box.appendChild(element);

    }

    updateStatuses();
}


function selectUser(user){

    selected = user;

    document
        .getElementById("chatName")
        .textContent =
            userLabel(user);

    document
        .getElementById("typing")
        .textContent = "";

    updateChatStatus();

    loadConversation();

    renderUsers(
        filterList(users)
    );

    if(window.innerWidth <= 800){

        document
            .getElementById("sidebar")
            .classList.add("closed");

    }
}


function updateStatuses(){

    for(const user of users){

        const el =
            document.getElementById(
                "status-" +
                safe(user.username)
            );

        if(!el){
            continue;
        }

        const online =
            window.onlineUsers.includes(
                user.username
            );

        el.textContent =
            online
                ? "آنلاین"
                : (
                    userStatus(user) ||
                    user.username
                );

        el.className =
            "ustatus" +
            (
                online
                    ? " online"
                    : ""
            );

    }

    updateChatStatus();
}


function updateChatStatus(){

    const el =
        document.getElementById(
            "chatStatus"
        );

    if(!selected){

        el.textContent = "";

        return;
    }

    const online =
        window.onlineUsers.includes(
            selected.username
        );

    el.textContent =
        online
            ? "آنلاین"
            : (
                userStatus(selected) ||
                "آفلاین"
            );
}


async function loadConversation(){

    if(!selected){
        return;
    }

    try{

        const data =
            await api(
                "/messages/" +
                encodeURIComponent(
                    selected.username
                )
            );

        renderMessages(
            data.messages || []
        );

    }catch(error){

        console.error(error);

    }
}


function renderMessages(list){

    const box =
        document.getElementById(
            "messages"
        );

    box.innerHTML = "";

    if(!list.length){

        box.innerHTML =
            '<div class="empty">هنوز پیامی در این گفت‌وگو وجود ندارد.<br>اولین پیام را بفرستید.</div>';

        return;
    }

    for(const message of list){

        addMessage(
            message,
            false
        );

    }

    scrollMessages();
}


function addMessage(message, scroll = true){

    const box =
        document.getElementById(
            "messages"
        );

    const empty =
        box.querySelector(
            ".empty"
        );

    if(empty){
        empty.remove();
    }

    const el =
        document.createElement("div");

    el.className =
        "msg " +
        (
            message.sender === me.username
                ? "mine"
                : "theirs"
        );

    el.innerHTML =
        '<span>' +
            esc(message.text) +
        '</span>' +

        '<span class="time">' +
            esc(message.created_at) +
        '</span>';

    box.appendChild(el);

    if(scroll){
        scrollMessages();
    }
}


function scrollMessages(){

    const box =
        document.getElementById(
            "messages"
        );

    box.scrollTop =
        box.scrollHeight;
}


function messageKey(event){

    if(
        event.key === "Enter" &&
        !event.shiftKey
    ){

        event.preventDefault();

        sendMessage();

    }

}


async function sendMessage(){

    if(!selected){

        alert(
            "ابتدا یک کاربر را انتخاب کنید."
        );

        return;
    }

    const input =
        document.getElementById(
            "messageInput"
        );

    const text =
        input.value.trim();

    if(!text){
        return;
    }

    if(
        socket &&
        socket.readyState === WebSocket.OPEN
    ){

        socket.send(
            JSON.stringify({
                type:"message",
                to:selected.username,
                text
            })
        );

        input.value = "";

        return;
    }

    try{

        const data =
            await api(
                "/messages",
                {
                    method:"POST",
                    headers:{
                        "Content-Type":
                            "application/json"
                    },
                    body:JSON.stringify({
                        receiver:
                            selected.username,
                        text
                    })
                }
            );

        addMessage(
            data.message,
            true
        );

        input.value = "";

    }catch(error){

        alert(error.message);

    }
}


function sendTyping(){

    if(
        !selected ||
        !socket ||
        socket.readyState !== WebSocket.OPEN
    ){
        return;
    }

    socket.send(
        JSON.stringify({
            type:"typing",
            to:selected.username,
            value:true
        })
    );

    clearTimeout(
        typingTimer
    );

    typingTimer =
        setTimeout(
            () => {

                if(
                    socket &&
                    socket.readyState === WebSocket.OPEN
                ){

                    socket.send(
                        JSON.stringify({
                            type:"typing",
                            to:selected.username,
                            value:false
                        })
                    );

                }

            },
            900
        );
}


function connectSocket(){

    if(!me){
        return;
    }

    if(
        socket &&
        (
            socket.readyState === WebSocket.OPEN ||
            socket.readyState === WebSocket.CONNECTING
        )
    ){
        return;
    }

    const protocol =
        location.protocol === "https:"
            ? "wss:"
            : "ws:";

    socket =
        new WebSocket(
            protocol +
            "//" +
            location.host +
            "/ws"
        );

    socket.onmessage =
        event => {

            let data;

            try{

                data =
                    JSON.parse(
                        event.data
                    );

            }catch(_){

                return;

            }

            if(
                data.type ===
                "online_users"
            ){

                window.onlineUsers =
                    data.users || [];

                updateStatuses();

                return;

            }

            if(
                data.type ===
                "typing"
            ){

                if(
                    selected &&
                    data.from ===
                        selected.username
                ){

                    document
                        .getElementById(
                            "typing"
                        )
                        .textContent =
                            data.value
                                ? "در حال نوشتن..."
                                : "";

                }

                return;

            }

            if(
                data.type ===
                "message"
            ){

                const message =
                    data.message;

                if(!message){
                    return;
                }

                if(
                    selected &&
                    (
                        (
                            message.sender ===
                            me.username &&
                            message.receiver ===
                            selected.username
                        )

                        ||

                        (
                            message.sender ===
                            selected.username &&
                            message.receiver ===
                            me.username
                        )
                    )
                ){

                    addMessage(
                        message,
                        true
                    );

                }

                return;

            }

            if(
                data.type === "error"
            ){

                console.error(
                    data.message
                );

            }

        };

    socket.onclose =
        () => {

            if(me){

                clearTimeout(
                    reconnectTimer
                );

                reconnectTimer =
                    setTimeout(
                        connectSocket,
                        2000
                    );

            }

        };
}


async function openProfile(){

    try{

        const data =
            await api(
                "/profile"
            );

        const p =
            data.profile || {};

        document
            .getElementById(
                "profileDisplayName"
            )
            .value =
                p.display_name ||
                me.username;

        document
            .getElementById(
                "profileStatus"
            )
            .value =
                p.status || "";

        selectedAvatarFile = null;
        removeAvatarFlag = false;

        const fileInput =
            document.getElementById(
                "profileAvatarFile"
            );

        fileInput.value = "";

        document
            .getElementById(
                "selectedFileName"
            )
            .textContent = "";

        previewCurrentAvatar(
            p.avatar,
            p.display_name ||
            me.username
        );

        profileErr("");

        document
            .getElementById(
                "profileModal"
            )
            .classList.remove(
                "hidden"
            );

    }catch(error){

        alert(
            error.message
        );

    }

}


function previewCurrentAvatar(
    avatar,
    name
){

    const box =
        document.getElementById(
            "profileAvatar"
        );

    if(avatar){

        box.innerHTML =
            '<img src="' +
            esc(avatar) +
            '" alt="">';

        return;

    }

    box.textContent =
        (
            name ||
            me?.username ||
            "؟"
        )
        .substring(0,1)
        .toUpperCase();

}


function handleAvatarSelect(event){

    const file =
        event.target.files &&
        event.target.files[0];

    if(!file){
        return;
    }

    const allowed = [
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp"
    ];

    if(!allowed.includes(file.type)){

        profileErr(
            "فقط JPG، PNG، GIF و WEBP مجاز است."
        );

        event.target.value = "";

        return;
    }

    if(file.size > 5 * 1024 * 1024){

        profileErr(
            "حجم عکس نباید بیشتر از ۵ مگابایت باشد."
        );

        event.target.value = "";

        return;
    }

    selectedAvatarFile = file;
    removeAvatarFlag = false;

    document
        .getElementById(
            "selectedFileName"
        )
        .textContent =
            file.name;

    const reader =
        new FileReader();

    reader.onload =
        () => {

            document
                .getElementById(
                    "profileAvatar"
                )
                .innerHTML =
                    '<img src="' +
                    esc(reader.result) +
                    '" alt="">';

        };

    reader.readAsDataURL(file);

    profileErr("");
}


function removeAvatar(){

    selectedAvatarFile = null;
    removeAvatarFlag = true;

    document
        .getElementById(
            "profileAvatarFile"
        )
        .value = "";

    document
        .getElementById(
            "selectedFileName"
        )
        .textContent =
            "عکس پروفایل حذف خواهد شد";

    const name =
        document
            .getElementById(
                "profileDisplayName"
            )
            .value
            .trim();

    document
        .getElementById(
            "profileAvatar"
        )
        .textContent =
            (
                name ||
                me?.username ||
                "؟"
            )
            .substring(0,1)
            .toUpperCase();

    profileErr("");
}


function closeProfile(){

    document
        .getElementById(
            "profileModal"
        )
        .classList.add(
            "hidden"
        );

    profileErr("");
}


async function saveProfile(){

    const displayName =
        document
            .getElementById(
                "profileDisplayName"
            )
            .value
            .trim();

    const status =
        document
            .getElementById(
                "profileStatus"
            )
            .value
            .trim();

    if(!displayName){

        profileErr(
            "نام نمایشی نمی‌تواند خالی باشد."
        );

        return;
    }

    try{

        profileErr(
            selectedAvatarFile
                ? "در حال آپلود عکس..."
                : "در حال ذخیره..."
        );

        if(selectedAvatarFile){

            const form =
                new FormData();

            form.append(
                "file",
                selectedAvatarFile
            );

            const uploadData =
                await api(
                    "/profile/avatar",
                    {
                        method:"POST",
                        body:form
                    }
                );

            me =
                uploadData.user;
        }

        const payload = {
            display_name:
                displayName,
            status,
        };

        if(removeAvatarFlag){

            payload.avatar = "";

        }

        const data =
            await api(
                "/profile",
                {
                    method:"PUT",
                    headers:{
                        "Content-Type":
                            "application/json"
                    },
                    body:JSON.stringify(
                        payload
                    )
                }
            );

        me =
            data.user;

        renderMe();

        await loadUsers();

        if(selected){

            const updated =
                users.find(
                    u =>
                        u.username ===
                        selected.username
                );

            if(updated){

                selected =
                    updated;

                document
                    .getElementById(
                        "chatName"
                    )
                    .textContent =
                        userLabel(
                            selected
                        );

                updateChatStatus();

            }

        }

        closeProfile();

    }catch(error){

        profileErr(
            error.message
        );

    }

}


document
    .getElementById(
        "profileDisplayName"
    )
    .addEventListener(
        "input",
        () => {

            if(
                !selectedAvatarFile &&
                !removeAvatarFlag
            ){

                const name =
                    document
                        .getElementById(
                            "profileDisplayName"
                        )
                        .value
                        .trim();

                const box =
                    document.getElementById(
                        "profileAvatar"
                    );

                const currentImage =
                    box.querySelector(
                        "img"
                    );

                if(!currentImage){

                    box.textContent =
                        (
                            name ||
                            me?.username ||
                            "؟"
                        )
                        .substring(
                            0,
                            1
                        )
                        .toUpperCase();

                }

            }

        }
    );


function toggleSidebar(){

    document
        .getElementById(
            "sidebar"
        )
        .classList.toggle(
            "closed"
        );

}


window.addEventListener(
    "load",
    async () => {

        try{

            const data =
                await api(
                    "/me"
                );

            if(data.user){

                await startApp();

            }

        }catch(_){}

    }
);

</script>

</body>
</html>'''


@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(HTML)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "app": APP_NAME,
        "time": now_text(),
    }


@app.get("/avatars/{filename}")
async def avatar_file(filename: str):

    clean_name = Path(filename).name

    if clean_name != filename:
        raise HTTPException(
            status_code=404,
            detail="عکس پیدا نشد.",
        )

    file_path = AVATARS_DIR / clean_name

    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail="عکس پیدا نشد.",
        )

    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="عکس پیدا نشد.",
        )

    return FileResponse(file_path)


@app.get("/me")
async def me_endpoint(request: Request):

    user = get_current_user(request)

    return {
        "authenticated": bool(user),
        "user": public_user(user) if user else None,
    }


@app.post("/register")
async def register(
    username: str = Form(...),
    password: str = Form(...),
):

    username = username.strip()

    if len(username) < 3:
        raise HTTPException(
            400,
            "نام کاربری باید حداقل ۳ کاراکتر باشد.",
        )

    if len(username) > 30:
        raise HTTPException(
            400,
            "نام کاربری نباید بیشتر از ۳۰ کاراکتر باشد.",
        )

    if not username.replace("_", "").isalnum():
        raise HTTPException(
            400,
            "نام کاربری فقط شامل حروف انگلیسی، عدد و _ باشد.",
        )

    if len(password) < 4:
        raise HTTPException(
            400,
            "رمز عبور باید حداقل ۴ کاراکتر باشد.",
        )

    with file_lock:

        users = load_users()

        if any(
            u.get("username", "").lower()
            == username.lower()
            for u in users
        ):
            raise HTTPException(
                400,
                "این نام کاربری قبلاً ثبت شده است.",
            )

        users.append(
            {
                "username": username,
                "password": hash_password(password),
                "created_at": now_text(),
                "profile": {
                    "display_name": username,
                    "status": "سلام، من در گپینو هستم",
                    "avatar": "",
                },
            }
        )

        save_json(
            USERS_FILE,
            users,
        )

    return {
        "ok": True,
        "message": "حساب با موفقیت ساخته شد.",
    }


@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):

    username = username.strip()

    for user in load_users():

        if user.get("username", "").lower() == username.lower():

            if verify_password(
                password,
                user.get("password", ""),
            ):

                ensure_profile(user)

                request.session["username"] = user["username"]

                return {
                    "ok": True,
                    "user": public_user(user),
                }

            break

    raise HTTPException(
        401,
        "نام کاربری یا رمز عبور اشتباه است.",
    )


@app.post("/logout")
async def logout(request: Request):

    request.session.clear()

    return {
        "ok": True,
    }


@app.get("/users")
async def users_endpoint(request: Request):

    current = get_current_user(request)

    if not current:
        raise HTTPException(
            401,
            "ابتدا وارد حساب شوید.",
        )

    with file_lock:

        all_users = load_users()
        changed = False
        result = []

        for user in all_users:

            before = json.dumps(
                user,
                ensure_ascii=False,
                sort_keys=True,
            )

            ensure_profile(user)

            after = json.dumps(
                user,
                ensure_ascii=False,
                sort_keys=True,
            )

            if before != after:
                changed = True

            if user.get("username") != current.get("username"):
                result.append(
                    public_user(user)
                )

        if changed:
            save_json(
                USERS_FILE,
                all_users,
            )

    return {
        "users": result,
    }


@app.get("/profile")
async def get_profile(request: Request):

    current = get_current_user(request)

    if not current:
        raise HTTPException(
            401,
            "ابتدا وارد حساب شوید.",
        )

    with file_lock:

        users = load_users()

        for user in users:

            if user.get("username") == current.get("username"):

                ensure_profile(user)

                save_json(
                    USERS_FILE,
                    users,
                )

                return {
                    "profile": public_profile(user),
                    "user": public_user(user),
                }

    raise HTTPException(
        404,
        "کاربر پیدا نشد.",
    )


@app.put("/profile")
async def update_profile(request: Request):

    current = get_current_user(request)

    if not current:
        raise HTTPException(
            401,
            "ابتدا وارد حساب شوید.",
        )

    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(
            400,
            "اطلاعات پروفایل نامعتبر است.",
        ) from exc

    display_name = str(
        data.get(
            "display_name",
            "",
        )
    ).strip()

    status = str(
        data.get(
            "status",
            "",
        )
    ).strip()

    avatar_value = data.get(
        "avatar",
        None,
    )

    if not display_name:
        raise HTTPException(
            400,
            "نام نمایشی نمی‌تواند خالی باشد.",
        )

    if len(display_name) > 50:
        raise HTTPException(
            400,
            "نام نمایشی نباید بیشتر از ۵۰ کاراکتر باشد.",
        )

    if len(status) > 150:
        raise HTTPException(
            400,
            "وضعیت نباید بیشتر از ۱۵۰ کاراکتر باشد.",
        )

    with file_lock:

        users = load_users()

        target = next(
            (
                u for u in users
                if u.get("username")
                == current.get("username")
            ),
            None,
        )

        if target is None:
            raise HTTPException(
                404,
                "کاربر پیدا نشد.",
            )

        ensure_profile(target)

        old_avatar = target["profile"].get(
            "avatar",
            "",
        )

        if avatar_value is None:

            new_avatar = old_avatar

        else:

            new_avatar = str(
                avatar_value
            ).strip()

            if new_avatar and not new_avatar.startswith(
                "/avatars/"
            ):
                raise HTTPException(
                    400,
                    "آدرس عکس پروفایل نامعتبر است.",
                )

        target["profile"] = {
            "display_name": display_name,
            "status": status,
            "avatar": new_avatar,
        }

        save_json(
            USERS_FILE,
            users,
        )

        if old_avatar != new_avatar:
            delete_avatar_file(old_avatar)

        updated = public_user(target)

    return {
        "ok": True,
        "profile": updated["profile"],
        "user": updated,
    }


@app.post("/profile/avatar")
async def upload_profile_avatar(
    request: Request,
    file: UploadFile = File(...),
):

    current = get_current_user(request)

    if not current:
        raise HTTPException(
            401,
            "ابتدا وارد حساب شوید.",
        )

    content_type = (
        file.content_type or ""
    ).lower().strip()

    if content_type not in ALLOWED_AVATAR_TYPES:
        raise HTTPException(
            400,
            "فقط فایل‌های JPG، PNG، GIF و WEBP مجاز هستند.",
        )

    try:

        content = await file.read()

    except Exception as exc:

        raise HTTPException(
            400,
            "خواندن فایل تصویر انجام نشد.",
        ) from exc

    if not content:

        raise HTTPException(
            400,
            "فایل تصویر خالی است.",
        )

    if len(content) > MAX_AVATAR_SIZE:

        raise HTTPException(
            400,
            "حجم عکس نباید بیشتر از ۵ مگابایت باشد.",
        )

    extension = ALLOWED_AVATAR_TYPES[content_type]

    filename = secrets.token_hex(20) + extension

    destination = AVATARS_DIR / filename

    try:

        with destination.open("wb") as f:
            f.write(content)

    except OSError as exc:

        raise HTTPException(
            500,
            "ذخیره عکس روی سرور انجام نشد.",
        ) from exc

    new_avatar = "/avatars/" + filename

    with file_lock:

        users = load_users()

        target = next(
            (
                u for u in users
                if u.get("username")
                == current.get("username")
            ),
            None,
        )

        if target is None:

            try:
                destination.unlink(
                    missing_ok=True
                )
            except OSError:
                pass

            raise HTTPException(
                404,
                "کاربر پیدا نشد.",
            )

        ensure_profile(target)

        old_avatar = target["profile"].get(
            "avatar",
            "",
        )

        target["profile"]["avatar"] = new_avatar

        save_json(
            USERS_FILE,
            users,
        )

        if old_avatar and old_avatar != new_avatar:
            delete_avatar_file(old_avatar)

        updated = public_user(target)

    return {
        "ok": True,
        "avatar": new_avatar,
        "profile": updated["profile"],
        "user": updated,
    }


@app.get("/messages/{username}")
async def get_messages(
    request: Request,
    username: str,
):

    current = get_current_user(request)

    if not current:
        raise HTTPException(
            401,
            "ابتدا وارد حساب شوید.",
        )

    if find_user(username) is None:
        raise HTTPException(
            404,
            "کاربر پیدا نشد.",
        )

    return {
        "messages": get_private_messages(
            current["username"],
            username,
        ),
    }


async def send_to_user(
    username,
    payload,
):

    with connections_lock:

        sockets = list(
            connections.get(
                username,
                set(),
            )
        )

    dead = []

    for websocket in sockets:

        try:

            await websocket.send_json(
                payload
            )

        except Exception:

            dead.append(
                websocket
            )

    if dead:

        with connections_lock:

            group = connections.get(
                username
            )

            if group is not None:

                for websocket in dead:
                    group.discard(
                        websocket
                    )

                if not group:
                    connections.pop(
                        username,
                        None
                    )


async def broadcast_online_users():

    with connections_lock:

        sockets = [
            ws
            for group in connections.values()
            for ws in list(group)
        ]

        online = list(
            connections.keys()
        )

    payload = {
        "type": "online_users",
        "users": online,
    }

    for websocket in sockets:

        try:

            await websocket.send_json(
                payload
            )

        except Exception:

            pass


async def store_message(
    sender: str,
    receiver: str,
    text: str,
):

    message = {
        "id": secrets.token_hex(12),
        "sender": sender,
        "receiver": receiver,
        "text": text,
        "created_at": now_text(),
    }

    with file_lock:

        messages = load_messages()

        messages.append(
            message
        )

        save_json(
            MESSAGES_FILE,
            messages[-10000:],
        )

    return message


@app.post("/messages")
async def create_message(
    request: Request,
):

    current = get_current_user(request)

    if not current:
        raise HTTPException(
            401,
            "ابتدا وارد حساب شوید.",
        )

    try:

        data = await request.json()

    except Exception as exc:

        raise HTTPException(
            400,
            "اطلاعات پیام نامعتبر است.",
        ) from exc

    receiver = str(
        data.get(
            "receiver",
            "",
        )
    ).strip()

    text = str(
        data.get(
            "text",
            "",
        )
    ).strip()

    if not receiver:

        raise HTTPException(
            400,
            "گیرنده مشخص نشده است.",
        )

    if not text:

        raise HTTPException(
            400,
            "متن پیام خالی است.",
        )

    if len(text) > 5000:

        raise HTTPException(
            400,
            "پیام بیش از حد طولانی است.",
        )

    if find_user(receiver) is None:

        raise HTTPException(
            404,
            "کاربر پیدا نشد.",
        )

    message = await store_message(
        current["username"],
        receiver,
        text,
    )

    payload = {
        "type": "message",
        "message": message,
    }

    await send_to_user(
        receiver,
        payload,
    )

    await send_to_user(
        current["username"],
        payload,
    )

    return {
        "ok": True,
        "message": message,
    }


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
):

    await websocket.accept()

    username = websocket.session.get(
        "username"
    )

    if (
        not username
        or find_user(username) is None
    ):

        await websocket.send_json(
            {
                "type": "error",
                "message": "ابتدا وارد حساب شوید.",
            }
        )

        await websocket.close()

        return

    with connections_lock:

        connections.setdefault(
            username,
            set(),
        ).add(
            websocket
        )

    await broadcast_online_users()

    try:

        while True:

            data = await websocket.receive_json()

            kind = data.get(
                "type"
            )

            if kind == "typing":

                target = str(
                    data.get(
                        "to",
                        "",
                    )
                ).strip()

                if (
                    target
                    and find_user(target) is not None
                ):

                    await send_to_user(
                        target,
                        {
                            "type": "typing",
                            "from": username,
                            "value": bool(
                                data.get(
                                    "value",
                                    False,
                                )
                            ),
                        },
                    )

            elif kind == "message":

                target = str(
                    data.get(
                        "to",
                        "",
                    )
                ).strip()

                text = str(
                    data.get(
                        "text",
                        "",
                    )
                ).strip()

                if not target or not text:
                    continue

                if len(text) > 5000:

                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": "پیام خیلی طولانی است.",
                        }
                    )

                    continue

                if find_user(target) is None:

                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": "کاربر پیدا نشد.",
                        }
                    )

                    continue

                message = await store_message(
                    username,
                    target,
                    text,
                )

                payload = {
                    "type": "message",
                    "message": message,
                }

                await send_to_user(
                    target,
                    payload,
                )

                await send_to_user(
                    username,
                    payload,
                )

    except WebSocketDisconnect:

        pass

    except Exception as exc:

        print(
            "WebSocket error:",
            repr(exc),
        )

    finally:

        with connections_lock:

            group = connections.get(
                username
            )

            if group is not None:

                group.discard(
                    websocket
                )

                if not group:

                    connections.pop(
                        username,
                        None
                    )

        await broadcast_online_users()


if __name__ == "__main__":

    import uvicorn

    port = int(
        os.getenv(
            "PORT",
            "8000",
        )
    )

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        reload=False,
    )