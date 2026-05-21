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


def configured_spiders():
    return os.getenv("SPIDERS", " ".join(DEFAULT_SPIDERS)).split()
