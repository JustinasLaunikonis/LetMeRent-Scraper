from pymongo import MongoClient

from api.config import MONGODB_COLLECTION, MONGODB_DATABASE, MONGODB_URI


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
