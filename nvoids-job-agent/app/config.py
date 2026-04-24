"""Application configuration.

Loaded once via `get_settings()` and cached. Values can be overridden with
environment variables (e.g. ``POLL_INTERVAL_MINUTES=10``) or a ``.env`` file.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_BODY_TEMPLATE = """Hi,

I hope you are doing well.

I am a Senior Data Engineer with 8 years of experience working with Databricks, PySpark, SQL, and Python.

Please find my resume attached for the Data Engineer position.

Please let me know if you need any additional information. I look forward to the opportunity to discuss how my skills align with your needs.

Best regards,
{your_name}
"""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    search_url: str = "https://nvoids.com/search_sph.jsp"
    # Term POSTed to the search form. Keep this narrow so nvoids returns the
    # 100-row window most relevant to us.
    search_val: str = "data engineer"
    poll_interval_minutes: int = 5
    db_path: str = "app/data/jobs.db"
    resume_dir: str = "app/data/resume"
    credentials_path: str = "credentials.json"
    base_url: str = "http://localhost:8000"

    # When None we fall back to ``scraper.DEFAULT_KEYWORDS`` at call sites.
    keywords: Optional[List[str]] = None

    your_name: str = "Your Name"
    default_subject: str = "Application for Data Engineer Position"
    default_body: str = DEFAULT_BODY_TEMPLATE

    @property
    def oauth_redirect_uri(self) -> str:
        return self.base_url.rstrip("/") + "/auth/callback"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
