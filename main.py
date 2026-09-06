# =========================
# LIVE STREAM API PART 1
# =========================


@app.post("/live/create")
async def create_live(request: Request):

    current = get_current_user(request)

    if not current:
        raise HTTPException(
            401,
            "ابتدا وارد حساب شوید."
        )

    try:
        data = await request.json()
    except Exception:
        data = {}


    title = str(
        data.get("title", "")
    ).strip()

    description = str(
        data.get("description", "")
    ).strip()


    if not title:
        raise HTTPException(
            400,
            "عنوان پخش زنده وارد نشده است."
        )


    live = db_create_live(
        current["username"],
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

    current = get_current_user(request)

    if not current:
        raise HTTPException(
            401,
            "ابتدا وارد حساب شوید."
        )


    live = db_get_live(
        live_id
    )


    if not live:
        raise HTTPException(
            404,
            "پخش زنده پیدا نشد."
        )


    if live["owner"] != current["username"]:
        raise HTTPException(
            403,
            "دسترسی ندارید."
        )


    updated = db_start_live(
        live_id
    )


    return {
        "ok": True,
        "live": updated
    }
# =========================
# LIVE STREAM API PART 2
# =========================


@app.post("/live/{live_id}/stop")
async def stop_live(
    request: Request,
    live_id: str
):

    current = get_current_user(request)

    if not current:
        raise HTTPException(
            401,
            "ابتدا وارد حساب شوید."
        )


    live = db_get_live(
        live_id
    )


    if not live:
        raise HTTPException(
            404,
            "پخش زنده پیدا نشد."
        )


    if live["owner"] != current["username"]:
        raise HTTPException(
            403,
            "دسترسی ندارید."
        )


    updated = db_stop_live(
        live_id
    )


    return {
        "ok": True,
        "live": updated
    }




@app.get("/live/list")
async def live_list(
    request: Request
):

    current = get_current_user(request)

    if not current:
        raise HTTPException(
            401,
            "ابتدا وارد حساب شوید."
        )


    lives = db_get_active_lives()


    return {
        "ok": True,
        "lives": lives
    }




@app.get("/live/{live_id}")
async def get_live_info(
    request: Request,
    live_id: str
):

    current = get_current_user(request)

    if not current:
        raise HTTPException(
            401,
            "ابتدا وارد حساب شوید."
        )


    live = db_get_live(
        live_id
    )


    if not live:
        raise HTTPException(
            404,
            "پخش زنده پیدا نشد."
        )


    return {
        "ok": True,
        "live": live
    }




@app.delete("/live/{live_id}")
async def delete_live(
    request: Request,
    live_id: str
):

    current = get_current_user(request)

    if not current:
        raise HTTPException(
            401,
            "ابتدا وارد حساب شوید."
        )


    live = db_get_live(
        live_id
    )


    if not live:
        raise HTTPException(
            404,
            "پخش زنده پیدا نشد."
        )


    if live["owner"] != current["username"]:
        raise HTTPException(
            403,
            "اجازه حذف این پخش را ندارید."
        )


    db_delete_live(
        live_id
    )


    return {
        "ok": True,
        "message": "پخش زنده حذف شد."
    }