from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

LONDON = ZoneInfo("Europe/London")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    base_url: str = "http://localhost:8000"
    secret_key: str = "dev-insecure-change-me"
    database_path: str = "data/courtwatch.db"
    admin_email: str = ""

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    mail_from: str = ""
    # Print emails to the log instead of sending them (also used when no SMTP password is set).
    mail_console: bool = False

    poll_enabled: bool = True
    poll_seconds: int = 300
    days_ahead: int = 14
    # Ignore slots that start sooner than this — too late to act on an alert.
    min_lead_minutes: int = 30
    contact_email: str = ""

    courtside_enabled: bool = False
    courtside_email: str = ""
    courtside_password: str = ""

    @property
    def secure_cookies(self) -> bool:
        return self.base_url.startswith("https://")

    @property
    def user_agent(self) -> str:
        contact = f"; {self.contact_email}" if self.contact_email else ""
        return f"CourtWatch/1.0 (personal court availability tracker{contact})"


@lru_cache
def get_settings() -> Settings:
    return Settings()
