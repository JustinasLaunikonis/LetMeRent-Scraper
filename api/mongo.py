from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from api.config import MONGODB_COLLECTION, MONGODB_DATABASE, MONGODB_URI, USERS_COLLECTION


class ListingRepository:
    def all(self):
        if not MONGODB_URI:
            raise RuntimeError("MONGODB_URI is not configured. Add it to LetMeRent/.env.")

        client = MongoClient(MONGODB_URI)
        try:
            return list(client[MONGODB_DATABASE][MONGODB_COLLECTION].find({}))
        finally:
            client.close()

    def find(self, query: dict, limit: int = 100, skip: int = 0):
        if not MONGODB_URI:
            raise RuntimeError("MONGODB_URI is not configured. Add it to LetMeRent/.env.")

        client = MongoClient(MONGODB_URI)
        try:
            cursor = client[MONGODB_DATABASE][MONGODB_COLLECTION].find(query)
            total = client[MONGODB_DATABASE][MONGODB_COLLECTION].count_documents(query)
            return list(cursor.skip(skip).limit(limit)), total
        finally:
            client.close()

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
