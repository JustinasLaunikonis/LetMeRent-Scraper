import os
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
SCRAPY_PROJECT_DIR = BASE_DIR / "LetMeRent"

if str(SCRAPY_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRAPY_PROJECT_DIR))

from LetMeRent.settings import (  # noqa: E402
    MONGODB_COLLECTION,
    MONGODB_DATABASE,
    MONGODB_URI,
)


DEFAULT_SPIDERS = ("funda", "housinganywhere", "huurwoningen", "irentalize", "kamernet")
USERS_COLLECTION = os.getenv("MONGODB_USERS_COLLECTION", "users")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ACCESS_TOKEN_EXPIRES_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES_MINUTES", "60"))


def configured_spiders():
    return os.getenv("SPIDERS", " ".join(DEFAULT_SPIDERS)).split()
