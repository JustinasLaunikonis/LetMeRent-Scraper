import logging
import os
import sys
from datetime import datetime, timezone


def configure_logging():
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
        force=True,
    )


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def docker_log(level: str, message: str):
    print(f"{utc_now()} {level} {message}", file=sys.stdout, flush=True)
