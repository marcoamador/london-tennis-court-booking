import asyncio

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app import auth
from app.main import run_poll, templates
from app.venues import all_venues

router = APIRouter(prefix="/admin")
_background: set[asyncio.Task] = set()  # keep references so tasks aren't garbage collected


@router.get("")
def admin_page(request: Request, msg: str = "", user=Depends(auth.require_admin)):
    with request.app.state.db.connect() as conn:
        invites = conn.execute("SELECT * FROM invites ORDER BY created_at DESC").fetchall()
        users = conn.execute(
            "SELECT u.*, (SELECT COUNT(*) FROM alert_rules r WHERE r.user_id = u.id) AS rules"
            " FROM users u ORDER BY u.created_at"
        ).fetchall()
        statuses = {
            r["venue_id"]: r for r in conn.execute("SELECT * FROM provider_status").fetchall()
        }
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "user": user,
            "invites": invites,
            "users": users,
            "statuses": statuses,
            "venues": all_venues(),
            "mail_console": request.app.state.mailer.console,
            "msg": msg,
        },
    )


@router.post("/invites")
def add_invite(request: Request, email: str = Form(...), user=Depends(auth.require_admin)):
    email = auth.normalize_email(email)
    if "@" in email:
        with request.app.state.db.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO invites (email, invited_by, created_at) VALUES (?, ?, ?)",
                (email, user["id"], auth.utcnow()),
            )
    return RedirectResponse(f"/admin?msg=Invited {email}", status_code=303)


@router.post("/invites/delete")
def remove_invite(request: Request, email: str = Form(...), user=Depends(auth.require_admin)):
    with request.app.state.db.connect() as conn:
        conn.execute("DELETE FROM invites WHERE email = ?", (email,))
    return RedirectResponse("/admin", status_code=303)


@router.post("/test-email")
async def test_email(request: Request, user=Depends(auth.require_admin)):
    try:
        await request.app.state.mailer.send(
            user["email"], "CourtWatch test email", "Email delivery works. 🎾"
        )
        msg = f"Test email sent to {user['email']}"
    except Exception as exc:
        msg = f"Sending failed: {exc!r}"
    return RedirectResponse(f"/admin?msg={msg}", status_code=303)


@router.post("/poll")
async def poll_now(request: Request, user=Depends(auth.require_admin)):
    task = asyncio.create_task(run_poll(request.app))
    _background.add(task)
    task.add_done_callback(_background.discard)
    return RedirectResponse("/admin?msg=Poll started — refresh in a few seconds", status_code=303)
