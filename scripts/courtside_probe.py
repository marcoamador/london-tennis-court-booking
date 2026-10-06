"""Check whether Courtside (tennistowerhamlets.com) serves booking pages to a logged-in script.

Run this yourself, on your own machine, with your own Courtside account:

    COURTSIDE_EMAIL=you@example.com COURTSIDE_PASSWORD=... uv run python -m scripts.courtside_probe

It never tries to solve or get around the Cloudflare "verify you're human" check: if any step is
redirected there, it stops and reports CHALLENGED. Only share the final verdict line, never your
password or cookies.
"""

import os
import sys
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx

BASE = "https://tennistowerhamlets.com"
BOOKING = f"{BASE}/book/courts/victoria-park"
UA = "CourtWatch-probe/1.0 (personal availability tracker)"


class FormParser(HTMLParser):
    """Collect the first form that has a password field."""

    def __init__(self):
        super().__init__()
        self.forms: list[dict] = []
        self._current: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self._current = {"action": a.get("action") or "", "fields": {}, "has_password": False}
        elif tag == "input" and self._current is not None:
            name = a.get("name")
            if a.get("type") == "password":
                self._current["has_password"] = True
                self._current["password_field"] = name
            elif a.get("type") == "email" or (name and "email" in name.lower()):
                self._current["email_field"] = name
            elif name:
                self._current["fields"][name] = a.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form" and self._current is not None:
            self.forms.append(self._current)
            self._current = None


def challenged(resp: httpx.Response) -> bool:
    location = resp.headers.get("location", "")
    return "verify-human" in location or "verify-human" in str(resp.url)


def verdict(text: str, code: int) -> None:
    print(f"\nVERDICT: {text}")
    sys.exit(code)


def main() -> None:
    email, password = os.environ.get("COURTSIDE_EMAIL"), os.environ.get("COURTSIDE_PASSWORD")
    if not email or not password:
        sys.exit("Set COURTSIDE_EMAIL and COURTSIDE_PASSWORD in your environment.")

    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=False, timeout=20) as client:
        anon = client.get(BOOKING)
        print(f"1. Anonymous booking page: HTTP {anon.status_code}, challenged={challenged(anon)}")

        login = client.get(f"{BASE}/login")
        print(f"2. Login page: HTTP {login.status_code}, challenged={challenged(login)}")
        if challenged(login):
            verdict("CHALLENGED — the login page itself is behind the human check.", 2)
        if login.status_code != 200:
            verdict(f"UNKNOWN — login page returned HTTP {login.status_code}.", 3)

        parser = FormParser()
        parser.feed(login.text)
        form = next((f for f in parser.forms if f["has_password"]), None)
        if not form or not form.get("email_field"):
            verdict("UNKNOWN — couldn't find the login form; the site layout may differ.", 3)

        data = dict(form["fields"])
        data[form["email_field"]] = email
        data[form["password_field"]] = password
        resp = client.post(urljoin(f"{BASE}/login", form["action"]), data=data)
        print(f"3. Login submit: HTTP {resp.status_code}, challenged={challenged(resp)}")
        if challenged(resp):
            verdict("CHALLENGED — logging in triggers the human check.", 2)

        booking = client.get(BOOKING)
        print(
            f"4. Booking page when logged in: HTTP {booking.status_code}, challenged={challenged(booking)}"
        )
        if challenged(booking):
            verdict(
                "CHALLENGED — even logged-in sessions get the human check. Keep the deep link.", 2
            )
        if booking.status_code == 200 and "victoria" in booking.text.lower():
            verdict("NOT CHALLENGED — logged-in sessions can read the booking page.", 0)
        verdict(f"UNKNOWN — booking page returned HTTP {booking.status_code}.", 3)


if __name__ == "__main__":
    main()
