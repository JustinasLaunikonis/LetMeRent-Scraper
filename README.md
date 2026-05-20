# LetMeRent-Scraper

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

Run a spider from the Scrapy project directory:

```bash
cd LetMeRent
scrapy crawl huurwoningen
```
