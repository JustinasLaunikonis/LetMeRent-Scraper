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
    if min_price is not None or max_price is not None:
        mongo_filter["price"] = {}
        if min_price is not None:
            mongo_filter["price"]["$gte"] = min_price  # $gte = "greater than or equal to"
        if max_price is not None:
            mongo_filter["price"]["$lte"] = max_price  # $lte = "less than or equal to"

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
        documents, total = listings.find(mongo_filter, limit=limit, skip=skip)
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
