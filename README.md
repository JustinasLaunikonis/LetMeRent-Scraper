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
  -H "Authorization: Bearer <access_token>" \
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
MONGODB_USERS_COLLECTION=users
MONGODB_UNIQUE_KEY=url
SPIDERS=funda housinganywhere huurwoningen irentalize kamernet
JWT_SECRET_KEY=replace-with-a-long-random-secret
JWT_ACCESS_TOKEN_EXPIRES_MINUTES=60
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

## Scraped fields per spider

Each spider below has its own table listing **every field it stores**. Fields
are saved exactly as the spider yields them, after which the MongoDB pipeline
adds a few common fields to every document (see below).

### How to read the tables

- A **+** in the first column means the field is **shared**: every spider
  stores it under the same name with the same meaning. These eleven shared
  fields are `url`, `title`, `city`, `price`, `living_area`, `availability`,
  `status`, `energy_label`, `description`, `images`, and `tags`.
- Fields **without** a + are specific to that one spider (or only used by a few
  sites), so they keep their own name.

### Common fields added to every document

These are not scraped from the websites. The MongoDB pipeline
(`LetMeRent/pipelines.py`) adds them to every listing, no matter which spider
produced it.

| Field        | Type      | Meaning                                                  |
|--------------|-----------|----------------------------------------------------------|
| `source`     | text      | Which spider scraped it (the spider name, e.g. `funda`)  |
| `scraped_at` | timestamp | When the listing was last scraped (updated every run)    |
| `created_at` | timestamp | When the listing was first stored                        |

### funda

| + | Field           | Type      | Meaning                                              |
|---|-----------------|-----------|------------------------------------------------------|
| + | `url`           | text      | Listing detail page URL                              |
| + | `title`         | text      | Listing title (the street address)                   |
|   | `address`       | text      | Street address                                       |
|   | `street`        | text      | Street name                                          |
| + | `city`          | text      | City name (Title Case)                               |
|   | `postal_city`   | text      | Postal code + city line, e.g. `7811 AB Emmen`        |
|   | `neighbourhood` | text      | Neighbourhood name                                   |
|   | `latitude`      | number    | Map latitude                                         |
|   | `longitude`     | number    | Map longitude                                        |
| + | `price`         | number    | Monthly rent (no `€`)                                |
| + | `living_area`   | number    | Living area in m² (no `m²`)                          |
|   | `plot_size`     | number    | Plot/lot area in m²                                  |
|   | `rooms`         | number    | Number of bedrooms                                   |
|   | `bedrooms`      | number    | Number of bedrooms                                   |
| + | `energy_label`  | text      | Energy grade (e.g. `A`), or `""`                     |
| + | `status`        | text      | Standard status word (`Available`, `Rented`, …)      |
| + | `availability`  | text      | Move-in text (e.g. `Available immediately`)          |
| + | `description`   | text      | Listing description                                  |
|   | `agent_person`  | text      | Contact person name                                  |
|   | `agent`         | text      | Estate agent name                                    |
|   | `agent_url`     | text      | Estate agent page URL                                |
|   | `phone`         | text      | Contact phone number                                 |
| + | `images`        | list      | Photo URLs                                           |
|   | `features`      | dict      | All feature rows from the page (label → value)       |
| + | `tags`          | list      | Short descriptive chips                              |

### housinganywhere

| + | Field            | Type   | Meaning                                              |
|---|------------------|--------|------------------------------------------------------|
| + | `url`            | text   | Listing detail page URL                              |
| + | `title`          | text   | Listing title                                        |
|   | `street`         | text   | Street address                                       |
| + | `city`           | text   | City name (Title Case)                               |
| + | `price`          | number | Monthly rent (no `€`)                                |
|   | `price_label`    | text   | Price period label, e.g. `per month`                 |
| + | `living_area`    | number | Living area in m²                                    |
|   | `housemates`     | number | Number of housemates                                 |
|   | `floor`          | number | Floor number                                         |
| + | `availability`   | text   | Move-in text                                         |
| + | `status`         | text   | Standard status word (derived from availability)     |
| + | `energy_label`   | text   | Always `""` (site has no energy label)               |
| + | `description`    | text   | Listing description                                  |
|   | `deposit_policy` | text   | Deposit policy chip, e.g. `No deposit`               |
|   | `property_type`  | text   | Kind of property, e.g. `Private room in house`       |
|   | `furnished`      | text   | Furnishing chip                                      |
|   | `facilities`     | list   | Facility / amenity names                             |
|   | `tenant_type`    | text   | Allowed tenant type, e.g. `Students only`            |
|   | `tenant_age`     | text   | Preferred tenant age range                           |
|   | `tenant_gender`  | text   | Preferred tenant gender                              |
| + | `images`         | list   | Photo URLs (`src`)                                   |
|   | `srcset_images`  | list   | Extra photo URLs taken from the image `srcset`       |
| + | `tags`           | list   | Short descriptive chips                              |

### huurwoningen

| + | Field               | Type   | Meaning                                           |
|---|---------------------|--------|---------------------------------------------------|
| + | `url`               | text   | Listing detail page URL                           |
| + | `title`             | text   | Listing title                                     |
|   | `address`           | text   | Street address                                    |
| + | `city`              | text   | City name (Title Case)                            |
| + | `price`             | number | Monthly rent (no `€`)                             |
| + | `living_area`       | number | Living/surface area in m²                         |
|   | `rooms`             | number | Number of rooms                                   |
|   | `bathrooms`         | number | Number of bathrooms                               |
|   | `floors`            | number | Number of floors                                  |
|   | `construction_year` | number | Year built                                        |
|   | `interior`          | text   | Furnishing / interior condition                   |
|   | `property_type`     | text   | Dwelling type                                     |
|   | `property_types`    | text   | Property type                                     |
|   | `construction_type` | text   | Construction type                                 |
|   | `balcony`           | text   | `Present` (or the site's value)                   |
|   | `roof_terrace`      | text   | `Present` (or the site's value)                   |
| + | `energy_label`      | text   | Energy grade, or `""`                             |
| + | `status`            | text   | Standard status word                              |
|   | `offered_since`     | text   | Date the listing was offered                      |
| + | `availability`      | text   | Move-in text (e.g. `Immediately`)                 |
|   | `upkeep`            | text   | Upkeep / state of maintenance                     |
| + | `description`       | text   | Listing description                               |
| + | `images`            | list   | Photo URLs (card + detail page)                   |
| + | `tags`              | list   | Short descriptive chips                           |

### irentalize

| + | Field            | Type   | Meaning                                              |
|---|------------------|--------|------------------------------------------------------|
| + | `url`            | text   | Property detail page URL                             |
| + | `title`          | text   | Listing title                                        |
| + | `city`           | text   | City name                                            |
|   | `city_filter`    | text   | City chosen in the site's filter                     |
|   | `listing_page`   | number | Result page number it was found on                   |
|   | `property_type`  | text   | Property type (from the page heading)                |
| + | `price`          | number | Monthly rent (starting price, else base rent)        |
|   | `starting_price` | number | "Starting from" price                                |
|   | `base_rent`      | number | Base rent                                            |
|   | `service_fee`    | number | Service fee                                          |
|   | `utilities`      | number | Utilities amount                                     |
| + | `living_area`    | number | Living area in m²                                    |
|   | `rooms`          | number | Number of rooms                                      |
|   | `bathrooms`      | number | Number of bathrooms                                  |
|   | `kitchens`       | number | Number of kitchens                                   |
|   | `toilets`        | number | Number of toilets                                    |
|   | `floors`         | number | Number of floors                                     |
|   | `furnished`      | text   | `Furnished` or `""`                                  |
| + | `energy_label`   | text   | Energy grade, or `""`                                |
| + | `status`         | text   | Standard status word                                 |
| + | `availability`   | text   | Always `""` (site shows status, not a move-in date)  |
| + | `description`    | text   | Listing description                                  |
|   | `landlord_name`  | text   | Landlord / author name                               |
| + | `images`         | list   | Photo URLs (logo removed)                            |
| + | `tags`           | list   | Short descriptive chips                              |

### kamernet

| + | Field              | Type   | Meaning                                            |
|---|--------------------|--------|----------------------------------------------------|
| + | `url`              | text   | Listing detail page URL                            |
| + | `title`            | text   | Listing title (the street)                         |
|   | `address`          | text   | Street address                                     |
|   | `street`           | text   | Street name                                        |
| + | `city`             | text   | City name                                          |
| + | `price`            | number | Monthly rent (no `€`)                              |
|   | `price_label`      | text   | Price period label, e.g. `/month incl. utilities`  |
| + | `living_area`      | number | Living area in m²                                  |
|   | `furnished`        | text   | Furnishing text                                    |
|   | `property_type`    | text   | Property type                                      |
| + | `availability`     | text   | Move-in date (e.g. `1 July`)                       |
| + | `status`           | text   | Always `Available` (site lists rentable rooms)     |
| + | `energy_label`     | text   | Energy grade, or `""`                              |
| + | `description`      | text   | Listing description                                |
|   | `amenities`        | list   | "What you'll get" amenities                        |
|   | `utilities`        | text   | `Incl. utilities` or `Excl. utilities`             |
|   | `deposit`          | number | Deposit amount                                     |
|   | `additional_costs` | number | Extra monthly costs                                |
|   | `rental_period`    | text   | Rental period text                                 |
|   | `ideal_tenant`     | dict   | Landlord's ideal-tenant rows (label → value)       |
|   | `landlord_name`    | text   | Landlord name                                      |
|   | `landlord_type`    | text   | Landlord type / status                             |
|   | `posted`           | text   | When the listing was posted                        |
| + | `images`           | list   | Photo URLs                                         |
| + | `tags`             | list   | Short descriptive chips                            |

## Flask API

Start the API from the repository root:

```sh
python3 app.py
```

The API entrypoint stays in `app.py`. The implementation lives in `api/`:

```text
api/routes.py         HTTP endpoints and request validation
api/auth.py           user registration, password hashing, JWT tokens, route guards
api/spider_jobs.py    background Scrapy job runner and Docker log streaming
api/mongo.py          MongoDB listing reads and user storage
api/serialization.py  MongoDB values converted for JSON responses
api/config.py         shared Scrapy and Mongo settings
```

### Chrono Tasks

`POST /chrono/tasks` accepts a JSON object with the required `user` field and these nullable search preferences:

```text
spider, city, university_campus, min_budget, max_budget, move_in_date,
min_lease_length, max_distance_from_campus, room_type, furnishing,
pet_friendly
```

`spider` is a comma-separated source string, for example `kamernet,funda`. If the frontend selects "Any source", send all spiders: `kamernet,funda,housinganywhere,huurwoningen,irentalize`. Empty text, select, and number fields may be sent as `null`; `pet_friendly` accepts `true`, `false`, or `null`. `move_in_date` must be `YYYY-MM-DD`; numeric fields must be greater than or equal to `0`.

The removed fields `time_between_scrap`, `time_between_scrap_minutes`, and `minimum_match_score` are not required and are ignored if present. `GET /chrono/tasks/user/{email}` returns the saved task in a `data` object.

### Auth

The API stores users in the MongoDB `users` collection by default. A user document contains the basic scalable fields:

```text
email, username, password_hash, roles, is_active, created_at, updated_at, last_login_at
```

`password_hash` is never returned by API responses. Set a strong `JWT_SECRET_KEY` before registering or logging in users.

Auth is JWT-based:

- `POST /auth/register` creates a user and returns an access token.
- `POST /auth/login` verifies the email and password, updates `last_login_at`, and returns an access token.
- `GET /auth/me` requires a valid token and returns the current user.
- Tokens are signed with `JWT_SECRET_KEY` using `HS256`.
- Token lifetime is controlled by `JWT_ACCESS_TOKEN_EXPIRES_MINUTES`.

Register a user:

```sh
curl -X POST http://localhost:5000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"change-this-password","username":"user"}'
```

Log in:

```sh
curl -X POST http://localhost:5000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"change-this-password"}'
```

Both register and login return this shape:

```json
{
  "access_token": "<jwt>",
  "token_type": "Bearer",
  "expires_at": "2026-05-23T12:00:00+00:00",
  "user": {
    "id": "...",
    "email": "user@example.com",
    "username": "user",
    "roles": ["user"],
    "is_active": true
  }
}
```

Use the returned JWT in the `Authorization` header on protected endpoints:

```sh
curl http://localhost:5000/auth/me \
  -H "Authorization: Bearer <access_token>"
```

#### `jwt_required` wrapper

Use the `@jwt_required()` wrapper from `api.auth` to protect Flask routes. Put it directly above the route function, below the Flask route decorator:

```python
@api.get("/auth/me")
@jwt_required()
def me():
    return jsonify({"user": json_safe(public_user(g.current_user))})
```

The wrapper expects this request header:

```text
Authorization: Bearer <access_token>
```

`@jwt_required()` does the following before the route handler runs:

- Reads the bearer token from the `Authorization` header.
- Decodes and validates the JWT with `JWT_SECRET_KEY`.
- Rejects expired or invalid tokens with `401`.
- Loads the user from MongoDB using the JWT `sub` claim.
- Rejects inactive or missing users with `401`.
- Stores the loaded user on Flask's `g.current_user`.

Inside a protected route, use `g.current_user` when you need the authenticated user:

```python
@api.post("/account/example")
@jwt_required()
def account_example():
    user_id = str(g.current_user["_id"])
    return jsonify({"user_id": user_id})
```

For role-gated endpoints, pass the required roles:

```python
@api.post("/admin/example")
@jwt_required(roles=("admin",))
def admin_example():
    return jsonify({"ok": True})
```

If the authenticated user does not have every required role, the wrapper returns `403` with `{"error": "insufficient permissions"}`.

Choose which routes require auth by adding `@jwt_required()` in `api/routes.py`. For example, `/auth/me` is currently protected. To require login before running spiders, add the wrapper back to `run_spiders`:

```python
@api.post("/spiders/run")
@jwt_required()
def run_spiders():
    ...
```

Run the configured spiders in the background:

```sh
curl -X POST http://localhost:5000/spiders/run \
  -H "Authorization: Bearer <access_token>"
```

Run the configured spiders for one city:

```sh
curl -X POST http://localhost:5000/spiders/run \
  -H "Authorization: Bearer <access_token>" \
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
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"spiders":["housinganywhere","kamernet"]}'
```

Fetch all MongoDB listings:

```sh
curl http://localhost:5000/data
```
