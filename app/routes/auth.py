import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import auth
from app.main import templates

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"user": auth.current_user(request)})


@router.post("/login")
async def login_submit(request: Request, email: str = Form(...)):
    settings, db = request.app.state.settings, request.app.state.db
    email = auth.normalize_email(email)
    if auth.is_allowed(db, settings, email):
        token = auth.create_login_token(db, settings, email)
        if token:
            link = f"{settings.base_url}/auth/verify?token={token}"
            try:
                await request.app.state.mailer.send(
                    email,
                    "Your CourtWatch sign-in link",
                    f"Sign in to CourtWatch: {link}\n\nThe link works once and expires in 15 minutes.",
                    f'<p><a href="{link}">Sign in to CourtWatch</a></p>'
                    "<p>The link works once and expires in 15 minutes.</p>",
                )
            except Exception:
                log.exception("Could not send login email")
    else:
        log.info("Login attempt from non-invited email")
    # Same response either way so the form doesn't reveal who is invited.
    return templates.TemplateResponse(request, "login_sent.html", {"user": None, "email": email})


@router.get("/auth/verify")
def verify_page(request: Request, token: str):
    # A confirm button (POST) stops email link scanners from burning the single-use token.
    email = auth.peek_login_token(request.app.state.settings, token)
    return templates.TemplateResponse(
        request, "verify.html", {"user": None, "token": token, "email": email}
    )


@router.post("/auth/verify")
def verify_submit(request: Request, token: str = Form(...)):
    settings = request.app.state.settings
    user_id = auth.consume_login_token(request.app.state.db, settings, token)
    if user_id is None:
        return templates.TemplateResponse(
            request, "verify.html", {"user": None, "token": None, "email": None}, status_code=400
        )
    response = RedirectResponse("/alerts", status_code=303)
    response.set_cookie(
        auth.SESSION_COOKIE,
        auth.session_cookie_value(settings, user_id),
        max_age=auth.SESSION_MAX_AGE,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
    )
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(auth.SESSION_COOKIE)
    return response
