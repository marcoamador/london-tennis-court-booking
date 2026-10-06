import pytest

from app.config import Settings
from app.db import Database
from app.mailer import Mailer


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        database_path=str(tmp_path / "test.db"),
        admin_email="admin@example.com",
        secret_key="test-secret",
        mail_console=True,
        poll_enabled=False,
        base_url="http://testserver",
    )


@pytest.fixture
def db(settings):
    database = Database(settings.database_path)
    database.init()
    return database


@pytest.fixture
def mailer(settings):
    return Mailer(settings)


@pytest.fixture
def user_id(db):
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO users (email, created_at) VALUES ('friend@example.com', 'now')"
        )
        return cur.lastrowid


def add_rule(
    db, user_id, venues="west-ham-park", weekdays="0,1,2,3,4,5,6", frm="00:00", to="23:59"
):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO alert_rules (user_id, venue_ids, weekdays, time_from, time_to, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'now')",
            (user_id, venues, weekdays, frm, to),
        )
