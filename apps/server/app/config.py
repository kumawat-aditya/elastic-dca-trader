"""
Application configuration loaded from environment / .env file.

Blueprint references:
  - Section 3.1  : ADMIN_KEY for Master EA auth
  - Section 9    : DATABASE_URL for PostgreSQL
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (apps/server/)
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://elastic_dca:elastic_dca_pass@localhost:5432/elastic_dca")
    ADMIN_KEY: str = os.getenv("ADMIN_KEY", "CHANGE_ME_TO_A_STRONG_SECRET")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))


settings = Settings()
