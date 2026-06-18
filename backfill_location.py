# One-time script: give existing listings a GeoJSON "location" point built from their latitude/longitude.
# Run it from the LetMeRent-Scraper folder:
#     python backfill_location.py
from pymongo import MongoClient

from api.config import MONGODB_COLLECTION, MONGODB_DATABASE, MONGODB_URI


def build_location_point(latitude, longitude):
    # MongoDB geo searches need a GeoJSON point with [longitude, latitude] order.
    # Return None when we do not have two real numbers to work with.
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


def main():
    if not MONGODB_URI:
        print("MONGODB_URI is not configured. Add it to LetMeRent/.env.")
        return

    client = MongoClient(MONGODB_URI)
    collection = client[MONGODB_DATABASE][MONGODB_COLLECTION]

    # Only look at listings that have coordinates but no location point yet.
    query = {
        "latitude": {"$exists": True, "$nin": [None, ""]},
        "longitude": {"$exists": True, "$nin": [None, ""]},
        "location": {"$exists": False},
    }

    updated = 0
    skipped = 0
    for listing in collection.find(query):
        point = build_location_point(listing.get("latitude"), listing.get("longitude"))
        if point is None:
            # The coordinates were not real numbers, so we cannot build a point.
            skipped = skipped + 1
            continue

        collection.update_one(
            {"_id": listing["_id"]},
            {"$set": {"location": point}},
        )
        updated = updated + 1

    print("Listings updated with a location point:", updated)
    print("Listings skipped (bad coordinates):", skipped)

    # Make sure the geo index exists so the distance filter is fast.
    collection.create_index([("location", "2dsphere")], background=True)
    print("2dsphere index is ready.")

    client.close()


if __name__ == "__main__":
    main()
