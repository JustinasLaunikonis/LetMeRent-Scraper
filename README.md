# LetMeRent-Scraper

## Docker

Build the API image:

```sh
docker build -t letmerent-scraper .
```

Run the Flask API:

```sh
docker run --rm -p 5000:5000 --env-file LetMeRent/.env letmerent-scraper
```

Run with Docker Compose:

```sh
docker compose up --build api
```

Then start spiders through the API:

```sh
curl -X POST http://localhost:5000/spiders/run \
  -H "Content-Type: application/json" \
  -d '{"city":"Amsterdam"}'
```

Docker Compose reads runtime settings from `LetMeRent/.env`. To use a different MongoDB service name or run only selected spiders, edit `MONGODB_URI` or `SPIDERS` there.

Write JSON results to a file on the host instead of MongoDB:

```sh
mkdir -p output
docker run --rm -w /app/LetMeRent --entrypoint scrapy \
  -v "$PWD/output:/output" letmerent-scraper \
  crawl housinganywhere -a city=Amsterdam -O /output/listings.json
```

## MongoDB Storage

Scraped items are stored in MongoDB through `LetMeRent.pipelines.MongoDBPipeline`.

Create `LetMeRent/.env` from `LetMeRent/.env.example` and set:

```env
MONGODB_URI=mongodb://localhost:27017
MONGODB_DATABASE=letmerent
MONGODB_COLLECTION=listings
MONGODB_UNIQUE_KEY=url
SPIDERS=funda housinganywhere huurwoningen irentalize kamernet
```

For Docker Compose, the scraper joins the external Docker network `mongodb_dev_net`. Use a network-reachable MongoDB hostname in `MONGODB_URI`, for example `mongodb://mongodb:27017`.

`MONGODB_UNIQUE_KEY` defaults to `url`, so repeated scraper runs update the same listing document instead of inserting duplicates.

Common fields shared across spiders use these names when the site provides the data:

```text
url, source, title, address, street, city, price, price_label, living_area,
rooms, property_type, availability, description, images, energy_label,
latitude, longitude
```

Site-specific data keeps its own field name, for example `agent_url`, `plot_size`, `city_filter`, `base_rent`, `service_fee`, `ideal_tenant`, and `srcset_images`.

Run a spider from the Scrapy project directory:

```sh
cd LetMeRent
scrapy crawl huurwoningen -a city=Amsterdam
```

## Flask API

Start the API from the repository root:

```sh
python3 app.py
```

The API entrypoint stays in `app.py`. The implementation lives in `api/`:

```text
api/routes.py         HTTP endpoints and request validation
api/spider_jobs.py    background Scrapy job runner and Docker log streaming
api/mongo.py          MongoDB listing reads
api/serialization.py  MongoDB values converted for JSON responses
api/config.py         shared Scrapy and Mongo settings
```

Run the configured spiders in the background:

```sh
curl -X POST http://localhost:5000/spiders/run
```

Run the configured spiders for one city:

```sh
curl -X POST http://localhost:5000/spiders/run \
  -H "Content-Type: application/json" \
  -d '{"city":"Amsterdam"}'
```

The response contains a `job.id`. Docker logs include `spider_job_*` lines for
job status, and Scrapy logs are streamed directly to the container output.

```sh
docker compose logs -f api
```

Run selected spiders:

```sh
curl -X POST http://localhost:5000/spiders/run \
  -H "Content-Type: application/json" \
  -d '{"spiders":["housinganywhere","kamernet"]}'
```

Fetch all MongoDB listings:

```sh
curl http://localhost:5000/data
```

Fetch listings by price with pagination:

```sh
curl "http://localhost:5000/data?min_price=800&max_price=1400&limit=50&skip=0"
```

For the fastest response when the UI does not need the total match count:

```sh
curl "http://localhost:5000/data?max_price=1200&include_count=false"
```

The API stores and queries a numeric `price_value` field and creates MongoDB
indexes for `price_value`, `source + price_value`, and `city_key + price_value`.
Existing documents are backfilled on the first API query after deployment.
