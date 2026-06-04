from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, g, jsonify, request
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


@api.post("/auth/register")
def register():
    payload = _request_payload()

    try:
        require_jwt_secret()
        user = create_user(
            email=payload.get("email"),
            password=payload.get("password"),
            username=payload.get("username"),
        )
        token, expires_at = create_access_token(user)
    except ValueError as exc:
        message = str(exc)
        status = 409 if "already exists" in message else 400
        return jsonify({"error": message}), status
    except (RuntimeError, PyMongoError) as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "access_token": token,
        "token_type": "Bearer",
        "expires_at": expires_at,
        "user": json_safe(public_user(user)),
    }), 201


@api.post("/auth/login")
def login():
    payload = _request_payload()
    try:
        user = authenticate_user(payload.get("email"), payload.get("password"))
    except (RuntimeError, PyMongoError) as exc:
        return jsonify({"error": str(exc)}), 500

    if not user:
        return jsonify({"error": "invalid email or password"}), 401

    try:
        token, expires_at = create_access_token(user)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "access_token": token,
        "token_type": "Bearer",
        "expires_at": expires_at,
        "user": json_safe(public_user(user)),
    })


@api.get("/auth/me")
@jwt_required()
def me():
    return jsonify({"user": json_safe(public_user(g.current_user))})


def _required_string(payload, field):
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        return None, f"{field} must be a non-empty string"

    return value.strip(), None


CHRONO_STRING_FIELDS = (
    "university_campus",
    "room_type",
    "furnishing",
)

CHRONO_NUMERIC_FIELDS = (
    "min_budget",
    "max_budget",
    "min_lease_length",
    "max_distance_from_campus",
    "minimum_match_score",
)


def _optional_number(payload, field):
    value = payload.get(field)
    if value is None or value == "":
        return None, None

    if isinstance(value, bool):
        return None, f"{field} must be a number"

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, f"{field} must be a number"

    if number < 0:
        return None, f"{field} must be greater than or equal to 0"

    if number.is_integer():
        return int(number), None

    return number, None


def _query_number(field):
    if field not in request.args:
        return None, None

    return _optional_number(request.args, field)


def _optional_bool(payload, field):
    value = payload.get(field)
    if value is None or value == "":
        return None, None

    if isinstance(value, bool):
        return value, None

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1", "yes"):
            return True, None
        if normalized in ("false", "0", "no"):
            return False, None

    return None, f"{field} must be a boolean"


def _optional_date(payload, field):
    value = payload.get(field)
    if value is None or value == "":
        return None, None

    if not isinstance(value, str):
        return None, f"{field} must be a date string in YYYY-MM-DD format"

    normalized = value.strip()
    try:
        date.fromisoformat(normalized)
    except ValueError:
        return None, f"{field} must be a date string in YYYY-MM-DD format"

    return normalized, None


def _chrono_task_payload():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, "request body must be a JSON object"

    task = {}
    for field in ("user", "spider", "city"):
        value, error = _required_string(payload, field)
        if error:
            return None, error
        task[field] = value

    time_between_scrap = payload.get("time_between_scrap")
    if time_between_scrap is None:
        time_between_scrap = payload.get("time_between_scrap_minutes")

    if not isinstance(time_between_scrap, int) or time_between_scrap < 1:
        return None, "time_between_scrap must be an integer greater than 0"

    for field in CHRONO_STRING_FIELDS:
        value = payload.get(field)
        if value is not None and value != "":
            if not isinstance(value, str):
                return None, f"{field} must be a string"
            task[field] = value.strip()

    for field in CHRONO_NUMERIC_FIELDS:
        value, error = _optional_number(payload, field)
        if error:
            return None, error
        if value is not None:
            task[field] = value

    if (
        task.get("min_budget") is not None
        and task.get("max_budget") is not None
        and task["min_budget"] > task["max_budget"]
    ):
        return None, "min_budget must be less than or equal to max_budget"

    move_in_date, error = _optional_date(payload, "move_in_date")
    if error:
        return None, error
    if move_in_date is not None:
        task["move_in_date"] = move_in_date

    pet_friendly, error = _optional_bool(payload, "pet_friendly")
    if error:
        return None, error
    if pet_friendly is not None:
        task["pet_friendly"] = pet_friendly

    now = datetime.now(timezone.utc)
    task["time_between_scrap"] = time_between_scrap
    task["created_at"] = now
    task["updated_at"] = now

    return task, None


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


@api.post("/chrono/tasks")
def create_chrono_task():
    task, error = _chrono_task_payload()
    if error:
        return jsonify({"error": error}), 400

    try:
        created_task = chrono_tasks.create(task)
    except (RuntimeError, PyMongoError) as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"task": json_safe(created_task)}), 201


@api.get("/chrono/tasks")
def get_chrono_tasks():
    mongo_filter = {}

    user = request.args.get("user")
    if user:
        mongo_filter["user"] = user.strip()

    spider = request.args.get("spider")
    if spider:
        mongo_filter["spider"] = spider.strip()

    city = request.args.get("city")
    if city:
        mongo_filter["city"] = {"$regex": city.strip(), "$options": "i"}

    for field in CHRONO_STRING_FIELDS:
        value = request.args.get(field)
        if value:
            mongo_filter[field] = {"$regex": value.strip(), "$options": "i"}

    for field in CHRONO_NUMERIC_FIELDS:
        value, error = _query_number(field)
        if error:
            return jsonify({"error": error}), 400
        if value is not None:
            mongo_filter[field] = value

    move_in_date = request.args.get("move_in_date")
    if move_in_date:
        mongo_filter["move_in_date"] = move_in_date.strip()

    pet_friendly = request.args.get("pet_friendly")
    if pet_friendly:
        value, error = _optional_bool({"pet_friendly": pet_friendly}, "pet_friendly")
        if error:
            return jsonify({"error": error}), 400
        mongo_filter["pet_friendly"] = value

    limit = request.args.get("limit", default=50, type=int)
    skip = request.args.get("skip", default=0, type=int)
    limit = max(1, min(limit, 500))

    try:
        documents, total = chrono_tasks.find(mongo_filter, limit=limit, skip=skip)
    except (RuntimeError, PyMongoError) as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "count": total,
        "returned": len(documents),
        "data": json_safe(documents),
    })


@api.get("/chrono/tasks/user/<path:user>")
def get_chrono_task_by_user(user):
    user = user.strip()
    if not user:
        return jsonify({"error": "user must be a non-empty string"}), 400

    try:
        task = chrono_tasks.get_by_user(user)
    except (RuntimeError, PyMongoError) as exc:
        return jsonify({"error": str(exc)}), 500

    if task is None:
        return jsonify({"error": "task not found"}), 404

    return jsonify({"task": json_safe(task)})


@api.get("/chrono/tasks/<task_id>")
def get_chrono_task(task_id):
    try:
        task = chrono_tasks.get(task_id)
    except (RuntimeError, PyMongoError) as exc:
        return jsonify({"error": str(exc)}), 500

    if task is None:
        return jsonify({"error": "task not found"}), 404

    return jsonify({"task": json_safe(task)})


@api.delete("/chrono/tasks/<task_id>")
def delete_chrono_task(task_id):
    try:
        deleted_count = chrono_tasks.delete(task_id)
    except (RuntimeError, PyMongoError) as exc:
        return jsonify({"error": str(exc)}), 500

    if deleted_count == 0:
        return jsonify({"error": "task not found"}), 404

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

    created_after = request.args.get("created_after")

    if created_after:
        try:
            created_after_date = datetime.fromisoformat(
                created_after.replace("Z", "+00:00")
            )
        except ValueError:
            return jsonify({"error": "created_after must be ISO datetime"}), 400

        mongo_filter["created_at"] = {
            "$gte": created_after_date
        }

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

@api.get("/spiders/jobs/<job_id>")
def get_spider_job(job_id):
    job = spider_jobs.get(job_id)

    if job is None:
        return jsonify({"error": "job not found"}), 404

    return jsonify({"job": json_safe(job)})
