from datetime import datetime, timezone

from bson import ObjectId
from pymongo import ASCENDING, MongoClient
from pymongo.collation import Collation
from pymongo.errors import CollectionInvalid

from api.config import (
    MONGODB_CHRONO_TASKS_COLLECTION,
    MONGODB_COLLECTION,
    MONGODB_DATABASE,
    MONGODB_URI,
)


NUMERIC_STRING_COLLATION = Collation(locale="en", numericOrdering=True)


CHRONO_TASKS_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["city", "spider", "max_price", "user", "schedule", "enabled", "status", "created_at", "updated_at"],
        "properties": {
            "city": {"bsonType": "string"},
            "spider": {"bsonType": "string"},
            "max_price": {"bsonType": ["int", "long", "double", "decimal"]},
            "user": {"bsonType": "string"},
            "min_price": {"bsonType": ["int", "long", "double", "decimal", "null"]},
            "schedule": {"bsonType": "string"},
            "timezone": {"bsonType": "string"},
            "enabled": {"bsonType": "bool"},
            "status": {"enum": ["active", "paused", "running", "failed", "completed"]},
            "last_run_at": {"bsonType": ["date", "null"]},
            "next_run_at": {"bsonType": ["date", "null"]},
            "last_error": {"bsonType": ["string", "null"]},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
        },
    }
}


class MongoRepository:
    def __init__(self):
        self._client = None

    @property
    def database(self):
        if not MONGODB_URI:
            raise RuntimeError("MONGODB_URI is not configured. Add it to LetMeRent/.env.")

        if self._client is None:
            self._client = MongoClient(MONGODB_URI)

        return self._client[MONGODB_DATABASE]


class ListingRepository(MongoRepository):
    def __init__(self):
        super().__init__()
        self._indexes_ready = False

    @property
    def collection(self):
        collection = self.database[MONGODB_COLLECTION]

        if not self._indexes_ready:
            self.ensure_indexes(collection)
            self._indexes_ready = True

        return collection

    def ensure_indexes(self, collection):
        collection.create_index([("price", ASCENDING)], background=True)
        collection.create_index([("source", ASCENDING), ("price", ASCENDING)], background=True)
        collection.create_index([("city", ASCENDING), ("price", ASCENDING)], background=True)
        collection.create_index(
            [("price", ASCENDING)],
            name="price_numeric_ordering",
            collation=NUMERIC_STRING_COLLATION,
            background=True,
        )
        collection.create_index(
            [("source", ASCENDING), ("price", ASCENDING)],
            name="source_price_numeric_ordering",
            collation=NUMERIC_STRING_COLLATION,
            background=True,
        )
        collection.create_index(
            [("city", ASCENDING), ("price", ASCENDING)],
            name="city_price_numeric_ordering",
            collation=NUMERIC_STRING_COLLATION,
            background=True,
        )

    def all(self):
        return list(self.collection.find({}))

    def find(self, query: dict, limit: int = 100, skip: int = 0, numeric_string_price: bool = False):
        collection = self.collection
        if numeric_string_price:
            cursor = collection.find(query, collation=NUMERIC_STRING_COLLATION)
            total = collection.count_documents(query, collation=NUMERIC_STRING_COLLATION)
        else:
            cursor = collection.find(query)
            total = collection.count_documents(query)
        return list(cursor.skip(skip).limit(limit)), total


class ChronoTaskRepository(MongoRepository):
    def __init__(self):
        super().__init__()
        self._collection_ready = False

    @property
    def collection(self):
        collection = self.database[MONGODB_CHRONO_TASKS_COLLECTION]

        if not self._collection_ready:
            self.ensure_collection()
            self._collection_ready = True

        return collection

    def ensure_collection(self):
        collection_names = self.database.list_collection_names()

        if MONGODB_CHRONO_TASKS_COLLECTION not in collection_names:
            try:
                self.database.create_collection(
                    MONGODB_CHRONO_TASKS_COLLECTION,
                    validator=CHRONO_TASKS_VALIDATOR,
                    validationLevel="moderate",
                )
            except CollectionInvalid:
                pass
        else:
            self.database.command({
                "collMod": MONGODB_CHRONO_TASKS_COLLECTION,
                "validator": CHRONO_TASKS_VALIDATOR,
                "validationLevel": "moderate",
            })

        collection = self.database[MONGODB_CHRONO_TASKS_COLLECTION]
        collection.create_index([("enabled", ASCENDING), ("next_run_at", ASCENDING)], background=True)
        collection.create_index([("user", ASCENDING), ("status", ASCENDING)], background=True)
        collection.create_index([("city", ASCENDING), ("spider", ASCENDING), ("max_price", ASCENDING)], background=True)

    def create(self, city, spider, max_price, user, schedule, **fields):
        now = datetime.now(timezone.utc)
        document = {
            "city": city.strip(),
            "spider": spider.strip(),
            "max_price": max_price,
            "user": user.strip(),
            "schedule": schedule.strip(),
            "timezone": fields.pop("timezone", "Europe/Amsterdam"),
            "enabled": fields.pop("enabled", True),
            "status": fields.pop("status", "active"),
            "min_price": fields.pop("min_price", None),
            "next_run_at": fields.pop("next_run_at", None),
            "last_run_at": fields.pop("last_run_at", None),
            "last_error": fields.pop("last_error", None),
            "created_at": now,
            "updated_at": now,
            **fields,
        }

        result = self.collection.insert_one(document)
        document["_id"] = result.inserted_id
        return document

    def find(self, query=None, limit=100, skip=0):
        query = query or {}
        cursor = self.collection.find(query).sort("created_at", -1)
        total = self.collection.count_documents(query)
        return list(cursor.skip(skip).limit(limit)), total

    def get(self, task_id):
        return self.collection.find_one({"_id": ObjectId(task_id)})

    def delete(self, task_id):
        result = self.collection.delete_one({"_id": ObjectId(task_id)})
        return result.deleted_count == 1
