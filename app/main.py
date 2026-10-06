import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import poller
from app.config import LONDON, Settings, get_settings
from app.db import Database
from app.mailer import Mailer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=HERE / "templates")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if settings.secret_key == "dev-insecure-change-me" and settings.secure_cookies:
        raise RuntimeError("Set SECRET_KEY before running with an https BASE_URL")

    db = Database(settings.database_path)
    db.init()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.http = poller.make_client(settings)
        scheduler = None
        if settings.poll_enabled:
            scheduler = AsyncIOScheduler(timezone=LONDON)
            scheduler.add_job(
                run_poll,
                "interval",
                seconds=settings.poll_seconds,
                jitter=20,
                max_instances=1,
                coalesce=True,
                next_run_time=datetime.now(LONDON) + timedelta(seconds=5),
                args=[app],
            )
            scheduler.start()
        yield
        if scheduler:
            scheduler.shutdown(wait=False)
        await app.state.http.aclose()

    app = FastAPI(title="CourtWatch", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.db = db
    app.state.mailer = Mailer(settings)

    @app.middleware("http")
    async def same_origin_posts(request: Request, call_next):
        # CSRF guard on top of SameSite=Lax cookies: browsers send Origin on cross-site POSTs.
        if request.method == "POST":
            origin = request.headers.get("origin")
            if (
                origin
                and origin != "null"
                and urlsplit(origin).netloc != request.headers.get("host")
            ):
                return PlainTextResponse("Cross-origin request blocked", status_code=403)
        return await call_next(request)

    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    from app.routes import admin, alerts, auth, pages

    for module in (pages, auth, alerts, admin):
        app.include_router(module.router)

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"ok": True}

    @app.get("/robots.txt", include_in_schema=False)
    def robots():
        return PlainTextResponse("User-agent: *\nDisallow: /\n")

    return app


async def run_poll(app: FastAPI) -> int:
    try:
        return await poller.poll_once(
            app.state.db, app.state.settings, app.state.mailer, app.state.http
        )
    except Exception:
        log.exception("Poll run failed")
        return 0


def __getattr__(name: str):
    # `uvicorn app.main:app` builds the app lazily so tests can call create_app() with settings.
    if name == "app":
        return create_app()
    raise AttributeError(name)
