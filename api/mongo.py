from pymongo import ASCENDING, MongoClient, UpdateOne

from api.config import MONGODB_COLLECTION, MONGODB_DATABASE, MONGODB_URI
from LetMeRent.normalization import normalized_text, price_value


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
        self.backfill_query_fields(collection)
        collection.create_index([("price_value", ASCENDING)], background=True)
        collection.create_index([("source", ASCENDING), ("price_value", ASCENDING)], background=True)
        collection.create_index([("city_key", ASCENDING), ("price_value", ASCENDING)], background=True)

    def backfill_query_fields(self, collection):
        operations = []
        query = {
            "$or": [
                {"price_value": {"$exists": False}},
                {"city_key": {"$exists": False}},
            ]
        }
        projection = {"price": 1, "city": 1, "source": 1}

        for document in collection.find(query, projection):
            update = {
                "price_value": price_value(document.get("price")),
                "city_key": normalized_text(document.get("city")),
            }

            source_key = normalized_text(document.get("source"))
            if source_key:
                update["source"] = source_key

            operations.append(UpdateOne({"_id": document["_id"]}, {"$set": update}))

            if len(operations) >= 1000:
                collection.bulk_write(operations, ordered=False)
                operations = []

        if operations:
            collection.bulk_write(operations, ordered=False)

    def close(self):
        if self._client is not None:
            self._client.close()
            self._client = None
            self._indexes_ready = False

    def all(self):
        return list(self.collection.find({}))

    def find(self, query: dict, limit: int = 100, skip: int = 0, include_count: bool = True):
        collection = self.collection
        cursor = collection.find(query).sort("price_value", ASCENDING)
        documents = list(cursor.skip(skip).limit(limit))
        total = collection.count_documents(query) if include_count else None

        return documents, total
