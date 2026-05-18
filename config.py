import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is not set")
    return value


QUO_BASE_URL = os.getenv("QUO_BASE_URL", "https://api.openphone.com")
QUO_API_KEY = require_env("QUO_API_KEY")
PHONE_NUMBER_ID = require_env("PHONE_NUMBER_ID")
BUSINESS_PHONE_NUMBER = os.getenv("BUSINESS_PHONE_NUMBER", "+12245760059")

GPT_SHARED_SECRET = os.getenv("GPT_SHARED_SECRET", "")
DATABASE_PATH = os.getenv("DATABASE_PATH") or "summaries.db"
MAX_CONVERSATIONS = int(os.getenv("MAX_CONVERSATIONS", "25"))
HTTP_TIMEOUT_SECONDS = int(os.getenv("HTTP_TIMEOUT_SECONDS", "30"))
