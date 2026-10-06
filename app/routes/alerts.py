from datetime import date, time

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth
from app.alerts import WEEKDAY_NAMES, Rule
from app.main import templates
from app.venues import all_venues, get_venue

router = APIRouter(prefix="/alerts")


def _venue_choices(request: Request):
    return all_venues()


def _insert_rule(db, user_id: int, venue_ids, weekdays, time_from: str, time_to: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO alert_rules (user_id, venue_ids, weekdays, time_from, time_to, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                user_id,
                ",".join(venue_ids),
                ",".join(str(d) for d in sorted(set(weekdays))),
                time_from,
                time_to,
                auth.utcnow(),
            ),
        )


@router.get("")
def list_rules(request: Request, user=Depends(auth.require_user)):
    with request.app.state.db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM alert_rules WHERE user_id = ? ORDER BY id DESC", (user["id"],)
        ).fetchall()
    rules = [(row, Rule.from_row(row)) for row in rows]
    return templates.TemplateResponse(
        request,
        "alerts.html",
        {
            "user": user,
            "rules": rules,
            "venues": _venue_choices(request),
            "venue_name": lambda vid: get_venue(vid).name if get_venue(vid) else vid,
            "weekday_names": WEEKDAY_NAMES,
        },
    )


@router.post("")
def create_rule(
    request: Request,
    venue_ids: list[str] = Form(...),
    weekdays: list[int] = Form(...),
    time_from: str = Form(...),
    time_to: str = Form(...),
    user=Depends(auth.require_user),
):
    valid = {v.id for v in _venue_choices(request)}
    venue_ids = [v for v in venue_ids if v in valid]
    weekdays = [d for d in weekdays if 0 <= d <= 6]
    try:
        start, end = time.fromisoformat(time_from), time.fromisoformat(time_to)
    except ValueError as exc:
        raise HTTPException(400, "Invalid time") from exc
    if not venue_ids or not weekdays or start >= end:
        raise HTTPException(400, "Pick at least one venue and day, and a valid time range")
    _insert_rule(
        request.app.state.db, user["id"], venue_ids, weekdays, f"{start:%H:%M}", f"{end:%H:%M}"
    )
    return RedirectResponse(request.app.state.settings.path("/alerts"), status_code=303)


@router.post("/quick")
def quick_rule(
    request: Request,
    venue_id: str = Form(...),
    day: date = Form(...),
    hour: int = Form(...),
    user=Depends(auth.require_user),
):
    if not get_venue(venue_id) or not 0 <= hour <= 23:
        raise HTTPException(400, "Unknown venue or hour")
    end = "23:59" if hour == 23 else f"{hour + 1:02d}:00"
    _insert_rule(
        request.app.state.db, user["id"], [venue_id], [day.weekday()], f"{hour:02d}:00", end
    )
    if request.headers.get("hx-request"):
        return HTMLResponse(
            '<td class="slot watching" title="You&#39;ll be emailed when a court frees up">'
            '<span><span class="bell">🔔</span><span class="lbl">watching</span></span></td>'
        )
    return RedirectResponse(request.app.state.settings.path("/alerts"), status_code=303)


@router.post("/{rule_id}/toggle")
def toggle_rule(request: Request, rule_id: int, user=Depends(auth.require_user)):
    with request.app.state.db.connect() as conn:
        conn.execute(
            "UPDATE alert_rules SET active = 1 - active WHERE id = ? AND user_id = ?",
            (rule_id, user["id"]),
        )
    return RedirectResponse(request.app.state.settings.path("/alerts"), status_code=303)


@router.post("/{rule_id}/delete")
def delete_rule(request: Request, rule_id: int, user=Depends(auth.require_user)):
    with request.app.state.db.connect() as conn:
        conn.execute("DELETE FROM alert_rules WHERE id = ? AND user_id = ?", (rule_id, user["id"]))
    return RedirectResponse(request.app.state.settings.path("/alerts"), status_code=303)


@router.post("/pause-all")
def toggle_pause(request: Request, user=Depends(auth.require_user)):
    with request.app.state.db.connect() as conn:
        conn.execute(
            "UPDATE users SET alerts_paused = 1 - alerts_paused WHERE id = ?", (user["id"],)
        )
    return RedirectResponse(request.app.state.settings.path("/alerts"), status_code=303)


@router.get("/pause")
def pause_page(request: Request, token: str):
    valid = auth.read_pause_token(request.app.state.settings, token) is not None
    return templates.TemplateResponse(
        request, "pause.html", {"user": None, "token": token, "valid": valid, "done": False}
    )


@router.post("/pause")
def pause_from_email(request: Request, token: str = Form(...)):
    user_id = auth.read_pause_token(request.app.state.settings, token)
    if user_id is not None:
        with request.app.state.db.connect() as conn:
            conn.execute("UPDATE users SET alerts_paused = 1 WHERE id = ?", (user_id,))
    return templates.TemplateResponse(
        request,
        "pause.html",
        {"user": None, "token": token, "valid": user_id is not None, "done": True},
    )
