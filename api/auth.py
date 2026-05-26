import re
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from bson import ObjectId
from flask import g, jsonify, request
from pymongo.errors import PyMongoError
from werkzeug.security import check_password_hash, generate_password_hash

from api.config import JWT_ACCESS_TOKEN_EXPIRES_MINUTES, JWT_SECRET_KEY
from api.mongo import UserRepository


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
users = UserRepository()


def _now():
    return datetime.now(timezone.utc)


def normalize_email(email):
    if not isinstance(email, str):
        return None
    email = email.strip().lower()
    return email if EMAIL_RE.match(email) else None


def public_user(user):
    return {
        "id": str(user["_id"]),
        "email": user["email"],
        "username": user.get("username"),
        "roles": user.get("roles", []),
        "is_active": user.get("is_active", True),
        "created_at": user.get("created_at"),
        "updated_at": user.get("updated_at"),
        "last_login_at": user.get("last_login_at"),
    }


def require_jwt_secret():
    if not JWT_SECRET_KEY:
        raise RuntimeError("JWT_SECRET_KEY is not configured. Add it to LetMeRent/.env.")


def create_user(email, password, username=None):
    email = normalize_email(email)
    if not email:
        raise ValueError("valid email is required")

    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("password must be at least 8 characters")

    if username is not None:
        username = username.strip()
        if not 3 <= len(username) <= 40:
            raise ValueError("username must be between 3 and 40 characters")

    created_at = _now()
    user = {
        "email": email,
        "password_hash": generate_password_hash(password),
        "roles": ["user"],
        "is_active": True,
        "created_at": created_at,
        "updated_at": created_at,
        "last_login_at": None,
    }
    if username:
        user["username"] = username

    return users.create(user)


def authenticate_user(email, password):
    email = normalize_email(email)
    if not email or not isinstance(password, str):
        return None

    user = users.find_by_email(email)
    if not user or not user.get("is_active", True):
        return None

    if not check_password_hash(user.get("password_hash", ""), password):
        return None

    logged_in_at = _now()
    users.update_last_login(user["_id"], logged_in_at)
    user["last_login_at"] = logged_in_at
    user["updated_at"] = logged_in_at
    return user


def create_access_token(user):
    require_jwt_secret()

    issued_at = _now()
    expires_at = issued_at + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRES_MINUTES)
    payload = {
        "sub": str(user["_id"]),
        "email": user["email"],
        "roles": user.get("roles", []),
        "iat": issued_at,
        "exp": expires_at,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256"), expires_at


def _bearer_token():
    auth_header = request.headers.get("Authorization", "")
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def load_user_from_token(token):
    require_jwt_secret()

    payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])
    user_id = payload.get("sub")
    if not ObjectId.is_valid(user_id):
        return None

    user = users.find_by_id(ObjectId(user_id))
    if not user or not user.get("is_active", True):
        return None

    return user


def jwt_required(roles=None):
    required_roles = set(roles or [])

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            token = _bearer_token()
            if not token:
                return jsonify({"error": "authorization bearer token is required"}), 401

            try:
                user = load_user_from_token(token)
            except jwt.ExpiredSignatureError:
                return jsonify({"error": "token has expired"}), 401
            except jwt.InvalidTokenError:
                return jsonify({"error": "token is invalid"}), 401
            except (RuntimeError, PyMongoError) as exc:
                return jsonify({"error": str(exc)}), 500

            if not user:
                return jsonify({"error": "token user is not active or does not exist"}), 401

            user_roles = set(user.get("roles", []))
            if required_roles and not required_roles.issubset(user_roles):
                return jsonify({"error": "insufficient permissions"}), 403

            g.current_user = user
            return view(*args, **kwargs)

        return wrapped

    return decorator
