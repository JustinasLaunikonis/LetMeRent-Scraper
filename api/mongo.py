from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collation import Collation
from pymongo.errors import DuplicateKeyError

from api.config import MONGODB_COLLECTION, MONGODB_DATABASE, MONGODB_URI, USERS_COLLECTION


NUMERIC_STRING_COLLATION = Collation(locale="en", numericOrdering=True)


class ListingRepository:
    def __init__(self):
        self._client = None
        self._indexes_ready = False

    @property
    def collection(self):
        if not MONGODB_URI:
            raise RuntimeError("MONGODB_URI is not configured. Add it to LetMeRent/.env.")

        if self._client is None:
            self._client = MongoClient(MONGODB_URI)

        collection = self._client[MONGODB_DATABASE][MONGODB_COLLECTION]

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

    def find(self, query: dict, limit: int = 100, skip: int = 0, numeric_string_price: bool = False, sort=None):
        collection = self.collection

        # Check if we are sorting by price, and remember which direction.
        sorts_by_price = False
        price_direction = ASCENDING
        if sort:
            for field, field_direction in sort:
                if field == "price":
                    sorts_by_price = True
                    price_direction = field_direction

        if sorts_by_price:
            # price is stored inconsistently across sources: Funda uses numbers
            # (17000) while others use numeric strings ("850"). MongoDB sorts
            # different BSON types in separate brackets (all numbers, then all
            # strings), so a plain .sort() effectively sorts each source on its
            # own. Convert price to a number first so every source sorts together
            # as one global list.
            direction = price_direction
            pipeline = [
                {"$match": query},
                {"$addFields": {
                    "_price_num": {
                        "$convert": {
                            "input": "$price",
                            "to": "double",
                            "onError": None,
                            "onNull": None,
                        }
                    }
                }},
                # Drop anything whose price could not be parsed to a real number.
                {"$match": {"_price_num": {"$ne": None}}},
                {"$sort": {"_price_num": direction}},
                {"$skip": skip},
                {"$limit": limit},
                {"$project": {"_price_num": 0}},
            ]
            documents = list(collection.aggregate(pipeline))
            total = collection.count_documents(query)
            return documents, total

        if numeric_string_price:
            cursor = collection.find(query, collation=NUMERIC_STRING_COLLATION)
            total = collection.count_documents(query, collation=NUMERIC_STRING_COLLATION)
        else:
            cursor = collection.find(query)
            total = collection.count_documents(query)
        if sort:
            cursor = cursor.sort(sort)
        return list(cursor.skip(skip).limit(limit)), total

    def delete_many(self, query: dict):
        if not MONGODB_URI:
            raise RuntimeError("MONGODB_URI is not configured. Add it to LetMeRent/.env.")

        client = MongoClient(MONGODB_URI)
        try:
            return client[MONGODB_DATABASE][MONGODB_COLLECTION].delete_many(query)
        finally:
            client.close()


class UserRepository:
    def _client(self):
        if not MONGODB_URI:
            raise RuntimeError("MONGODB_URI is not configured. Add it to LetMeRent/.env.")

        return MongoClient(MONGODB_URI)

    def _collection(self, client):
        collection = client[MONGODB_DATABASE][USERS_COLLECTION]
        collection.create_index("email", unique=True)
        collection.create_index("username", sparse=True)
        return collection

    def create(self, user: dict):
        client = self._client()
        try:
            collection = self._collection(client)
            result = collection.insert_one(user)
            return collection.find_one({"_id": result.inserted_id})
        except DuplicateKeyError as exc:
            raise ValueError("user with this email already exists") from exc
        finally:
            client.close()

    def find_by_email(self, email: str):
        client = self._client()
        try:
            return self._collection(client).find_one({"email": email.lower()})
        finally:
            client.close()

    def find_by_id(self, user_id):
        client = self._client()
        try:
            return self._collection(client).find_one({"_id": user_id})
        finally:
            client.close()

    def update_last_login(self, user_id, logged_in_at):
        client = self._client()
        try:
            self._collection(client).update_one(
                {"_id": user_id},
                {"$set": {"last_login_at": logged_in_at, "updated_at": logged_in_at}},
            )
        finally:
            client.close()


class ChronoTaskRepository:
    def __init__(self):
        self._client = None
        self._indexes_ready = False

    @property
    def collection(self):
        if not MONGODB_URI:
            raise RuntimeError("MONGODB_URI is not configured. Add it to LetMeRent/.env.")

        if self._client is None:
            self._client = MongoClient(MONGODB_URI)

        collection = self._client[MONGODB_DATABASE]["chrono_tasks"]

        if not self._indexes_ready:
            self.ensure_indexes(collection)
            self._indexes_ready = True

        return collection

    def ensure_indexes(self, collection):
        self.delete_duplicate_user_tasks(collection)
        self.ensure_unique_user_index(collection)
        collection.create_index([("spider", ASCENDING), ("city", ASCENDING)], background=True)
        collection.create_index([("university_campus", ASCENDING)], background=True)
        collection.create_index([("room_type", ASCENDING), ("furnishing", ASCENDING)], background=True)
        collection.create_index([("pet_friendly", ASCENDING)], background=True)

    def ensure_unique_user_index(self, collection):
        existing_index = collection.index_information().get("user_1")
        if existing_index and not existing_index.get("unique"):
            collection.drop_index("user_1")

        collection.create_index([("user", ASCENDING)], background=True, unique=True)

    def delete_duplicate_user_tasks(self, collection):
        duplicates = collection.aggregate([
            {"$sort": {"_id": -1}},
            {
                "$group": {
                    "_id": "$user",
                    "keep": {"$first": "$_id"},
                    "delete": {"$push": "$_id"},
                    "count": {"$sum": 1},
                }
            },
            {"$match": {"_id": {"$ne": None}, "count": {"$gt": 1}}},
        ])

        for duplicate in duplicates:
            task_ids = [task_id for task_id in duplicate["delete"] if task_id != duplicate["keep"]]
            if task_ids:
                collection.delete_many({"_id": {"$in": task_ids}})

    def create(self, task: dict):
        collection = self.collection
        collection.delete_many({"user": task["user"]})

        try:
            result = collection.insert_one(task)
        except DuplicateKeyError:
            collection.delete_many({"user": task["user"]})
            result = collection.insert_one(task)

        return collection.find_one({"_id": result.inserted_id})

    def find(self, query: dict, limit: int = 100, skip: int = 0):
        cursor = self.collection.find(query).sort("_id", ASCENDING)
        total = self.collection.count_documents(query)
        return list(cursor.skip(skip).limit(limit)), total

    def get(self, task_id: str):
        if not ObjectId.is_valid(task_id):
            return None

        return self.collection.find_one({"_id": ObjectId(task_id)})

    def get_by_user(self, user: str):
        return self.collection.find_one({"user": user})

    def delete(self, task_id: str):
        if not ObjectId.is_valid(task_id):
            return 0

        result = self.collection.delete_one({"_id": ObjectId(task_id)})
        return result.deleted_count
