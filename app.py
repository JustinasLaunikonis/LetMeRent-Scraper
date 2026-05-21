from __future__ import annotations

import os
import logging
import subprocess
import sys
import threading
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from bson import ObjectId
from flask import Flask, jsonify, request
from pymongo import MongoClient
from pymongo.errors import PyMongoError


BASE_DIR = Path(__file__).resolve().parent
SCRAPY_PROJECT_DIR = BASE_DIR / "LetMeRent"

sys.path.insert(0, str(SCRAPY_PROJECT_DIR))

from LetMeRent.settings import (  # noqa: E402
    MONGODB_COLLECTION,
    MONGODB_DATABASE,
    MONGODB_URI,
)


DEFAULT_SPIDERS = ("funda", "housinganywhere", "huurwoningen", "irentalize", "kamernet")

app = Flask(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

_job_lock = threading.Lock()
_current_job: dict[str, Any] | None = None


def _configured_spiders() -> list[str]:
    return os.getenv("SPIDERS", " ".join(DEFAULT_SPIDERS)).split()


def _json_safe(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, list):
        return [_json_safe(item) for item in value]

    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}

    return value


def _mongo_collection():
    if not MONGODB_URI:
        raise RuntimeError("MONGODB_URI is not configured. Add it to LetMeRent/.env.")

    client = MongoClient(MONGODB_URI)
    return client, client[MONGODB_DATABASE][MONGODB_COLLECTION]


def _run_spider_job(job_id: str, spiders: list[str], extra_args: list[str]) -> None:
    results = []
    app.logger.info("spider_job_started job_id=%s spiders=%s args=%s", job_id, ",".join(spiders), extra_args)

    for spider in spiders:
        app.logger.info("spider_job_spider_started job_id=%s spider=%s", job_id, spider)
        spider_started_at = datetime.utcnow().isoformat() + "Z"
        command = [sys.executable, "-m", "scrapy", "crawl", spider, *extra_args]
        completed = subprocess.run(
            command,
            cwd=SCRAPY_PROJECT_DIR,
            check=False,
        )
        results.append(
            {
                "spider": spider,
                "status": "completed" if completed.returncode == 0 else "failed",
                "returncode": completed.returncode,
                "started_at": spider_started_at,
                "finished_at": datetime.utcnow().isoformat() + "Z",
            }
        )

        if completed.returncode == 0:
            app.logger.info("spider_job_spider_completed job_id=%s spider=%s", job_id, spider)
        else:
            app.logger.error(
                "spider_job_spider_failed job_id=%s spider=%s returncode=%s",
                job_id,
                spider,
                completed.returncode,
            )

        if completed.returncode != 0:
            break

    status = "completed" if all(result["returncode"] == 0 for result in results) else "failed"
    app.logger.info("spider_job_finished job_id=%s status=%s", job_id, status)

    with _job_lock:
        global _current_job
        _current_job = {
            "id": job_id,
            "status": status,
            "spiders": spiders,
            "results": results,
            "finished_at": datetime.utcnow().isoformat() + "Z",
        }


@app.post("/spiders/run")
def run_spiders():
    payload = request.get_json(silent=True) or {}
    spiders = payload.get("spiders") or _configured_spiders()
    extra_args = payload.get("args") or []
    city = payload.get("city")

    if isinstance(spiders, str):
        spiders = spiders.split()

    if not isinstance(spiders, list) or not all(isinstance(item, str) for item in spiders):
        return jsonify({"error": "spiders must be a string or a list of strings"}), 400

    if not isinstance(extra_args, list) or not all(isinstance(item, str) for item in extra_args):
        return jsonify({"error": "args must be a list of strings"}), 400

    if city is not None:
        if not isinstance(city, str) or not city.strip():
            return jsonify({"error": "city must be a non-empty string"}), 400
        extra_args = [*extra_args, "-a", f"city={city.strip()}"]

    job_id = str(uuid.uuid4())

    with _job_lock:
        global _current_job
        if _current_job and _current_job.get("status") == "running":
            return jsonify({"error": "spiders are already running", "job": _current_job}), 409

        _current_job = {
            "id": job_id,
            "status": "running",
            "spiders": spiders,
            "started_at": datetime.utcnow().isoformat() + "Z",
        }

    thread = threading.Thread(target=_run_spider_job, args=(job_id, spiders, extra_args), daemon=True)
    thread.start()

    return jsonify({"job": _current_job}), 202


@app.get("/data")
def get_data():
    try:
        client, collection = _mongo_collection()
        try:
            documents = list(collection.find({}))
        finally:
            client.close()
    except (RuntimeError, PyMongoError) as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"count": len(documents), "data": _json_safe(documents)})


if __name__ == "__main__":
    app.run(host=os.getenv("FLASK_HOST", "0.0.0.0"), port=int(os.getenv("FLASK_PORT", "5000")))
