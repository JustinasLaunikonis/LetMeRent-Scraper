from pymongo import ASCENDING, MongoClient
from pymongo.collation import Collation

from api.config import MONGODB_COLLECTION, MONGODB_DATABASE, MONGODB_URI


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

    def find(self, query: dict, limit: int = 100, skip: int = 0, numeric_string_price: bool = False):
        collection = self.collection
        if numeric_string_price:
            cursor = collection.find(query, collation=NUMERIC_STRING_COLLATION)
            total = collection.count_documents(query, collation=NUMERIC_STRING_COLLATION)
        else:
            cursor = collection.find(query)
            total = collection.count_documents(query)
        return list(cursor.skip(skip).limit(limit)), total
