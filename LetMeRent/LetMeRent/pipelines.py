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


class LetmerentPipeline:
    def process_item(self, item, spider):
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
