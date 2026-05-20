````md
# LetMeRent-Scraper

## Docker

Build the image:

```sh
docker build -t letmerent-scraper .
````

Run the default spider:

```sh
docker run --rm letmerent-scraper
```

Run the spider for a specific city:

```sh
docker run --rm letmerent-scraper crawl housinganywhere -a city=Amsterdam--Netherlands
```

Write results to a file on the host:

```sh
mkdir -p output
docker run --rm -v "$PWD/output:/output" letmerent-scraper crawl housinganywhere -a city=Amsterdam--Netherlands -O /output/listings.json
```

## MongoDB storage

Scraped items are stored in MongoDB through `LetMeRent.pipelines.MongoDBPipeline`.

Create `LetMeRent/.env` from `LetMeRent/.env.example` and set:

```env
MONGODB_URI=mongodb://localhost:27017
MONGODB_DATABASE=letmerent
MONGODB_COLLECTION=listings
MONGODB_UNIQUE_KEY=url
```

`MONGODB_UNIQUE_KEY` defaults to `url`, so repeated scraper runs update the same listing document instead of inserting duplicates.

Common fields shared across spiders use these names when the site provides the data:

```text
url, source, title, address, street, city, price, price_label, living_area,
rooms, property_type, availability, description, images, energy_label,
latitude, longitude
```

Site-specific data keeps its own field name, for example `agent_url`, `plot_size`, `city_filter`, `base_rent`, `service_fee`, `ideal_tenant`, and `srcset_images`.

Run a spider from the Scrapy project directory:

```bash
cd LetMeRent
scrapy crawl huurwoningen
```

```
```
