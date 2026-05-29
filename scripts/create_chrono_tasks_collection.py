#!/usr/bin/env python3
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from api.config import MONGODB_CHRONO_TASKS_COLLECTION, MONGODB_DATABASE  # noqa: E402
from api.mongo import ChronoTaskRepository  # noqa: E402


def main():
    repository = ChronoTaskRepository()
    repository.ensure_collection()
    print(f"Created or updated {MONGODB_DATABASE}.{MONGODB_CHRONO_TASKS_COLLECTION}")


if __name__ == "__main__":
    main()
