from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from bson.errors import InvalidId
from pymongo.errors import PyMongoError

from api.auth import (
    authenticate_user,
    create_access_token,
    create_user,
    jwt_required,
    public_user,
    require_jwt_secret,
)
from api.config import configured_spiders
from api.mongo import ChronoTaskRepository, ListingRepository
from api.serialization import json_safe
from api.spider_jobs import SpiderJobRunner
from datetime import datetime, timedelta, timezone


api = Blueprint("api", __name__)
listings = ListingRepository()
chrono_tasks = ChronoTaskRepository()
spider_jobs = SpiderJobRunner()


def _price_string(value):
    if value is None:
        return None

    if float(value).is_integer():
        return str(int(value))

    return str(value)


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


def _chrono_payload():
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def _required_string(payload, field):
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _optional_datetime(payload, field):
    value = payload.get(field)
    if value is None:
        return None, None

    if isinstance(value, datetime):
        return value, None

    if not isinstance(value, str) or not value.strip():
        return None, f"{field} must be an ISO datetime string"

    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None, f"{field} must be an ISO datetime string"

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed, None


@api.post("/spiders/run")
#@jwt_required()
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


@api.post("/chrono")
def create_chrono_task():
    payload = _chrono_payload()

    city = _required_string(payload, "city")
    spider = _required_string(payload, "spider")
    user = _required_string(payload, "user")
    schedule = _required_string(payload, "schedule")
    max_price = payload.get("max_price")

    if not city or not spider or not user or not schedule:
        return jsonify({"error": "city, spider, user and schedule are required strings"}), 400

    if not isinstance(max_price, (int, float)) or isinstance(max_price, bool):
        return jsonify({"error": "max_price is required and must be a number"}), 400

    optional_fields = {}
    for field in ("timezone", "enabled", "status", "last_error"):
        if field in payload:
            optional_fields[field] = payload[field]

    if "min_price" in payload:
        min_price = payload["min_price"]
        if min_price is not None and (not isinstance(min_price, (int, float)) or isinstance(min_price, bool)):
            return jsonify({"error": "min_price must be a number or null"}), 400
        optional_fields["min_price"] = min_price

    if "enabled" in payload and not isinstance(payload["enabled"], bool):
        return jsonify({"error": "enabled must be a boolean"}), 400

    for field in ("next_run_at", "last_run_at"):
        if field in payload:
            parsed, error = _optional_datetime(payload, field)
            if error:
                return jsonify({"error": error}), 400
            optional_fields[field] = parsed

    try:
        task = chrono_tasks.create(
            city=city,
            spider=spider,
            max_price=max_price,
            user=user,
            schedule=schedule,
            **optional_fields,
        )
    except (RuntimeError, PyMongoError) as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"task": json_safe(task)}), 201


@api.get("/chrono")
def get_chrono_tasks():
    query = {}

    user = request.args.get("user")
    if user:
        query["user"] = user.strip()

    status = request.args.get("status")
    if status:
        query["status"] = status.strip()

    limit = request.args.get("limit", default=100, type=int)
    skip = request.args.get("skip", default=0, type=int)
    limit = max(1, min(limit, 500))
    skip = max(0, skip)

    try:
        tasks, total = chrono_tasks.find(query, limit=limit, skip=skip)
    except (RuntimeError, PyMongoError) as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "count": total,
        "returned": len(tasks),
        "data": json_safe(tasks),
    })


@api.get("/chrono/<task_id>")
def get_chrono_task(task_id):
    try:
        task = chrono_tasks.get(task_id)
    except InvalidId:
        return jsonify({"error": "invalid task id"}), 400
    except (RuntimeError, PyMongoError) as exc:
        return jsonify({"error": str(exc)}), 500

    if not task:
        return jsonify({"error": "chrono task not found"}), 404

    return jsonify({"task": json_safe(task)})


@api.delete("/chrono/<task_id>")
def delete_chrono_task(task_id):
    try:
        deleted = chrono_tasks.delete(task_id)
    except InvalidId:
        return jsonify({"error": "invalid task id"}), 400
    except (RuntimeError, PyMongoError) as exc:
        return jsonify({"error": str(exc)}), 500

    if not deleted:
        return jsonify({"error": "chrono task not found"}), 404

    return "", 204


@api.get("/data")
def get_data():
    # This is the global filter that will be sent to the database.
    # It starts empty so "return everything".
    # We add conditions/tags to it based on what the user wants in the URL.
    # Example: /data?city=emmen&max_price=1000&limit=50
    mongo_filter = {}

    # CITY FILTER
    # If the URL is ?city=something, only return listings in that city.
    city = request.args.get("city")
    if city:
        mongo_filter["city"] = {"$regex": city.strip(), "$options": "i"}

    # SOURCE FILTER
    # If the URL contains ?source=kamernet, only return listings from that website.
    source = request.args.get("source")
    if source:
        mongo_filter["source"] = source.strip().lower()

    # PRICE FILTER
    # If the URL contains ?min_price=500 and/or ?max_price=1200
    # only return listings of that price range.
    min_price = request.args.get("min_price", type=float)
    max_price = request.args.get("max_price", type=float)
    numeric_string_price = min_price is not None or max_price is not None
    if min_price is not None or max_price is not None:
        numeric_price_filter = {}
        string_price_filter = {}
        if min_price is not None:
            numeric_price_filter["$gte"] = min_price  # $gte = "greater than or equal to"
            string_price_filter["$gte"] = _price_string(min_price)
        if max_price is not None:
            numeric_price_filter["$lte"] = max_price  # $lte = "less than or equal to"
            string_price_filter["$lte"] = _price_string(max_price)

        mongo_filter["$or"] = [
            {"price": numeric_price_filter},
            {"price": string_price_filter},
        ]

    # PAGINATION
    # Instead of returning all 56mb's of listings at once, we return them in pages
    # ?limit=50 = "show 50 listings"
    # ?skip=50 = "skip first 50" (used to see/get page 2, 3, etc.)
    # cap the limit at 500 so nobody can request zillions of data at once.
    limit = request.args.get("limit", default=50, type=int)
    skip = request.args.get("skip", default=0, type=int)
    limit = max(1, min(limit, 500))

    # FETCH FROM DATABASE
    # If something goes wrong, return an error message.
    try:
        documents, total = listings.find(
            mongo_filter,
            limit=limit,
            skip=skip,
            numeric_string_price=numeric_string_price,
        )
    except (RuntimeError, PyMongoError) as exc:
        return jsonify({"error": str(exc)}), 500

    # RETURN THE RESULT
    # Send back a JSON with:
    # - count: total number of listings that match the filter (in the whole database)
    # - returned: how many listings are in this response
    # - data: the actual listings
    return jsonify({
        "count": total,
        "returned": len(documents),
        "data": json_safe(documents)
    })

@api.get("/listings/old")
def delete_old_listings():

    # Get the "days" query parameter from the URL.
    # Example:
    # /listings/old?days=7
    #
    # If the user does not provide "days",
    # the default value will be 30.
    #
    # type=int automatically converts the value to an integer.
    days = request.args.get("days", default=30, type=int)

    # Validation:
    # If the value is invalid, return HTTP 400 Bad Request.
    if days <= 0:
        return jsonify({"error": "days must be greater than 0"}), 400

    # Calculate the cutoff date.
    # Example: Current date: 2026-05-24 days=30 cutoff_date becomes: 2026-04-24 Listings older than this date are considered old.
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

    mongo_filter = {
        "created_at": {
            "$lt": cutoff_date
        }
    }

    # dry_run safety mode.
    # By default: dry_run=true Only show how many listings WOULD be deleted.

    dry_run = request.args.get("dry_run", default="true").lower() == "true"

    try:

        # Find old listings using the MongoDB filter.
        # We only request 1 document because: we do not need all listings here.
        documents, total = listings.find(
            mongo_filter,
            limit=1,
            skip=0
        )
        # PREVIEW MODE
        # If dry_run=true: Return only preview information.
        if dry_run:
            return jsonify({
                "dry_run": True,
                "message": "No listings were deleted. This is only a preview.",
                "older_than_days": days,
                "cutoff_date": cutoff_date.isoformat(),
                "would_delete": total
            })

        # REAL DELETE
        # If dry_run=false:actually remove matching listings from MongoDB .delete_many() removes ALL documents matching the mongo_filter.
        delete_result = listings.delete_many(mongo_filter)

    # Handle MongoDB or runtime errors.
    except (RuntimeError, PyMongoError) as exc:
        return jsonify({"error": str(exc)}), 500

    # Return successful deletion response.
    return jsonify({
        "dry_run": False,
        "message": "Old listings deleted successfully.",
        "older_than_days": days,
        "cutoff_date": cutoff_date.isoformat(),
        "deleted": delete_result.deleted_count
    })