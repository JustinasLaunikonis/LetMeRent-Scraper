# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface
from datetime import datetime, timezone

from itemadapter import ItemAdapter
from pymongo import ASCENDING, MongoClient
from pymongo.errors import PyMongoError
from scrapy.exceptions import NotConfigured

from LetMeRent.spiders.city_utils import normalize_availability


DEPRECATED_FIELDS = (
    "available_from",
    "furnishing",
    "home_type",
    "image",
    "lat",
    "lng",
    "price_suffix",
    "size",
)


def build_location_point(latitude, longitude):
    # MongoDB geo searches ("within X km of a point") need the coordinates as a GeoJSON point.
    if latitude is None or longitude is None:
        return None

    try:
        lat_number = float(latitude)
        lng_number = float(longitude)
    except (TypeError, ValueError):
        return None

    point = {
        "type": "Point",
        "coordinates": [lng_number, lat_number],
    }
    return point


class NormalizePipeline:
    # This pipeline runs for every scraped item, before it is stored.
    # It makes sure shared fields are always saved in the universal format,
    # no matter which spider produced the item. Each spider already tries to
    # normalise its own values, but this is a safety net so the database can
    # never keep a raw value like "Available on 7/1/2026" or "From 01-09-2026".
    def process_item(self, item, spider):
        adapter = ItemAdapter(item)

        # Turn the move-in date into the universal "YYYY-MM-DD" / "Immediately"
        # form. Running this again on an already-clean value leaves it the same.
        if "availability" in adapter:
            raw_value = adapter.get("availability")
            adapter["availability"] = normalize_availability(raw_value)

        return item


class MongoDBPipeline:
    def __init__(self, uri, database, collection, unique_key):
        self.uri = uri
        self.database_name = database
        self.collection_name = collection
        self.unique_key = unique_key
        self.client = None
        self.collection = None

    @classmethod
    def from_crawler(cls, crawler):
        uri = crawler.settings.get("MONGODB_URI")
        database = crawler.settings.get("MONGODB_DATABASE")
        collection = crawler.settings.get("MONGODB_COLLECTION")
        unique_key = crawler.settings.get("MONGODB_UNIQUE_KEY")

        if not uri:
            raise NotConfigured("MONGODB_URI is not configured. Add it to LetMeRent/.env.")

        if not database or not collection:
            raise NotConfigured("MONGODB_DATABASE and MONGODB_COLLECTION must be configured.")

        return cls(uri, database, collection, unique_key)

    def open_spider(self, spider):
        self.client = MongoClient(self.uri)
        self.collection = self.client[self.database_name][self.collection_name]

        if self.unique_key:
            self.collection.create_index(
                [(self.unique_key, ASCENDING)],
                unique=True,
                sparse=True,
                background=True,
            )

        self.collection.create_index([("price", ASCENDING)], background=True)
        self.collection.create_index([("source", ASCENDING), ("price", ASCENDING)], background=True)
        self.collection.create_index([("city", ASCENDING), ("price", ASCENDING)], background=True)
        self.collection.create_index([("location", "2dsphere")], background=True)

        spider.logger.info(
            "MongoDB pipeline connected to %s.%s",
            self.database_name,
            self.collection_name,
        )

    def close_spider(self, spider):
        if self.client:
            self.client.close()

    def process_item(self, item, spider):
        document = ItemAdapter(item).asdict()
        now = datetime.now(timezone.utc)

        document.setdefault("source", spider.name)
        document["scraped_at"] = now

        # Build a GeoJSON point from the latitude/longitude so the API can do "within X km of a campus" searches
        latitude = document.get("latitude")
        longitude = document.get("longitude")
        location_point = build_location_point(latitude, longitude)
        if location_point is not None:
            document["location"] = location_point

        try:
            unique_value = document.get(self.unique_key) if self.unique_key else None

            if unique_value:
                self.collection.update_one(
                    {self.unique_key: unique_value},
                    {
                        "$set": document,
                        "$setOnInsert": {"created_at": now},
                        "$unset": {field: "" for field in DEPRECATED_FIELDS},
                    },
                    upsert=True,
                )
            else:
                document["created_at"] = now
                self.collection.insert_one(document)
        except PyMongoError as exc:
            spider.logger.error("Failed to store item in MongoDB: %s", exc)
            raise

        return item
