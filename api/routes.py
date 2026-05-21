from flask import Blueprint, jsonify, request
from pymongo.errors import PyMongoError

from api.config import configured_spiders
from api.mongo import ListingRepository
from api.serialization import json_safe
from api.spider_jobs import SpiderJobRunner


api = Blueprint("api", __name__)
listings = ListingRepository()
spider_jobs = SpiderJobRunner()


def _request_payload():
    payload = request.get_json(silent=True)

    if payload is None:
        payload = request.get_json(force=True, silent=True)

    if not isinstance(payload, dict):
        payload = {}

    for key in ("city", "spiders"):
        value = request.values.get(key)
        if value is not None:
            payload[key] = value

    return payload


@api.post("/spiders/run")
def run_spiders():
    payload = _request_payload()
    spiders = payload.get("spiders") or configured_spiders()
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
        city = city.strip()

    job, running_job = spider_jobs.start(spiders, city=city, extra_args=extra_args)
    if running_job:
        return jsonify({"error": "spiders are already running", "job": running_job}), 409

    return jsonify({"job": job}), 202


@api.get("/data")
def get_data():
    try:
        documents = listings.all()
    except (RuntimeError, PyMongoError) as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"count": len(documents), "data": json_safe(documents)})
