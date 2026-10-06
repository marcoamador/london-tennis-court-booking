import re

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def sign_in(client, app, email="admin@example.com"):
    client.post("/login", data={"email": email})
    mail = app.state.mailer.outbox[-1]
    token = re.search(r"token=([\w\-.]+)", mail.text).group(1)
    assert "Continue as" in client.get(f"/auth/verify?token={token}").text
    resp = client.post("/auth/verify", data={"token": token}, follow_redirects=False)
    assert resp.status_code == 303
    return token


def test_home_page_shows_all_venues_as_cards(client):
    html = client.get("/").text
    for name in ("West Ham Park", "Stratford Park", "Lee Valley — outdoor", "Victoria Park"):
        assert f"<h2>{name}</h2>" in html
    assert html.count('<details class="card venue"') == 5


def test_venue_tab_shows_one_venue(client):
    html = client.get("/?venue=stratford-park").text
    assert "<h2>Stratford Park</h2>" in html and "<h2>West Ham Park</h2>" not in html


def test_untracked_venue_shows_deep_link(client):
    html = client.get("/?venue=victoria-park").text
    assert "<h2>Victoria Park</h2>" in html
    assert "tennistowerhamlets.com/book/courts/victoria-park" in html


def test_grid_cells_render(client, app):
    with app.state.db.connect() as conn:
        conn.executemany(
            'INSERT INTO slots (key, venue_id, court, date, start, "end", spaces, updated_at)'
            " VALUES (?, 'west-ham-park', ?, date('now', '+1 day'), '18:00', '19:00', ?, 'x')",
            [("a", "Court 1", 1), ("b", "Court 2", 1), ("c", "Court 3", 0)],
        )
        conn.execute(
            'INSERT INTO slots (key, venue_id, court, date, start, "end", spaces, updated_at)'
            " VALUES ('d', 'west-ham-park', 'Court 1', date('now', '+1 day'), '19:00', '20:00', 0, 'x')"
        )
    html = client.get("/?venue=west-ham-park").text
    assert '<span class="n">2</span><span class="lbl">courts</span>' in html
    assert "6 PM" in html and "7 PM" in html
    assert 'class="slot booked clickable"' in html


def test_filter_links_have_no_empty_params_and_all_work(client):
    html = client.get("/?days=14&period=evening&weekend=1&venue=stratford-park").text
    links = set(re.findall(r'href="(/\?[^"]*|/)"', html))
    assert len(links) > 5
    for href in links:
        href = href.replace("&amp;", "&")
        assert not re.search(r"=(&|$)", href), href
        assert client.get(href).status_code == 200, href


@pytest.mark.parametrize(
    "query", ["?days=", "?days=&period=&weekend=", "?days=abc&period=bogus&venue=nope", "?days=99"]
)
def test_bad_or_empty_filter_params_fall_back_to_defaults(client, query):
    assert client.get("/" + query).status_code == 200


def test_alerts_require_login(client):
    resp = client.get("/alerts", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/login"


def test_magic_link_sign_in_and_single_use(client, app):
    token = sign_in(client, app)
    assert client.get("/alerts").status_code == 200
    assert "admin@example.com" in client.get("/alerts").text
    # Token can't be reused.
    other = TestClient(app)
    assert other.post("/auth/verify", data={"token": token}).status_code == 400


def test_uninvited_email_gets_no_link(client, app):
    resp = client.post("/login", data={"email": "stranger@example.com"})
    assert "Check your email" in resp.text
    assert app.state.mailer.outbox == []


def test_invited_friend_can_sign_in_but_not_admin(client, app):
    sign_in(client, app)
    client.post("/admin/invites", data={"email": "Friend@Example.com"})
    friend = TestClient(app)
    sign_in(friend, app, "friend@example.com")
    assert friend.get("/alerts").status_code == 200
    assert friend.get("/admin").status_code == 403


def test_create_and_quick_rules(client, app):
    sign_in(client, app)
    client.post(
        "/alerts",
        data={
            "venue_ids": ["west-ham-park", "stratford-park"],
            "weekdays": ["5", "6"],
            "time_from": "17:00",
            "time_to": "20:00",
        },
    )
    resp = client.post(
        "/alerts/quick",
        data={"venue_id": "lee-valley-outdoor", "day": "2026-10-10", "hour": "18"},
        headers={"HX-Request": "true"},
    )
    assert "🔔" in resp.text
    with app.state.db.connect() as conn:
        rules = conn.execute("SELECT * FROM alert_rules ORDER BY id").fetchall()
    assert [r["venue_ids"] for r in rules] == ["west-ham-park,stratford-park", "lee-valley-outdoor"]
    assert (rules[1]["weekdays"], rules[1]["time_from"], rules[1]["time_to"]) == (
        "5",
        "18:00",
        "19:00",
    )


def test_cross_origin_post_blocked(client):
    resp = client.post(
        "/login", data={"email": "a@b.c"}, headers={"Origin": "https://evil.example"}
    )
    assert resp.status_code == 403
