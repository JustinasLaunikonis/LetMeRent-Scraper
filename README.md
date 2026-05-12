# LetMeRent-Scraper

## Docker

Build the image:

```sh
docker build -t letmerent-scraper .
```

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
