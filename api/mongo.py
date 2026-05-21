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
