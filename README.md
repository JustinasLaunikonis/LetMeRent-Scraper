# LetMeRent-Scraper

## Docker

Build the scraper image:

```sh
docker build -t letmerent-scraper .
```

Run the default spider:

```sh
docker run --rm letmerent-scraper
```

Run one spider for a specific city:

```sh
docker run --rm letmerent-scraper crawl housinganywhere -a city=Amsterdam--Netherlands
```

Run all spiders and save scraped data in MongoDB on the external Docker network `mongodb_dev_net`:

```sh
docker compose up --build scraper
```

By default, the scraper connects to `mongodb://mongodb:27017`. If your MongoDB container has a different service name or network alias, override it:

```sh
MONGODB_URI=mongodb://mongo:27017 docker compose up --build scraper
```

Run only selected spiders:

```sh
SPIDERS="housinganywhere kamernet" docker compose up --build scraper
```

Write JSON results to a file on the host instead of MongoDB:

```sh
mkdir -p output
docker run --rm -v "$PWD/output:/output" letmerent-scraper crawl housinganywhere -a city=Amsterdam--Netherlands -O /output/listings.json
```

## MongoDB Storage

Scraped items are stored in MongoDB through `LetMeRent.pipelines.MongoDBPipeline`.

Create `LetMeRent/.env` from `LetMeRent/.env.example` and set:

```env
MONGODB_URI=mongodb://localhost:27017
MONGODB_DATABASE=letmerent
MONGODB_COLLECTION=listings
MONGODB_UNIQUE_KEY=url
```

For Docker Compose, the scraper joins the external Docker network `mongodb_dev_net` and uses `mongodb://mongodb:27017` by default.

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
scrapy crawl huurwoningen
```
