import logging
from dataclasses import dataclass
from email.message import EmailMessage

import aiosmtplib

from app.config import Settings

log = logging.getLogger(__name__)


@dataclass
class SentMail:
    to: str
    subject: str
    text: str
    html: str | None


class Mailer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.outbox: list[SentMail] = []  # filled in console mode; handy for tests and dev

    @property
    def console(self) -> bool:
        return self.settings.mail_console or not self.settings.smtp_password

    async def send(self, to: str, subject: str, text: str, html: str | None = None) -> None:
        if self.console:
            self.outbox.append(SentMail(to, subject, text, html))
            log.warning("Console mail to %s: %s\n%s", to, subject, text)
            return
        msg = EmailMessage()
        msg["From"] = self.settings.mail_from or self.settings.smtp_username
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        if html:
            msg.add_alternative(html, subtype="html")
        await aiosmtplib.send(
            msg,
            hostname=self.settings.smtp_host,
            port=self.settings.smtp_port,
            start_tls=True,
            username=self.settings.smtp_username,
            password=self.settings.smtp_password,
            timeout=30,
        )
