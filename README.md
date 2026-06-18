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

## Scraped listing data

The spiders store plain listing documents in MongoDB. The frontend reads those documents through the Flask API and uses some fields directly, some fields only for filters or tag generation, and some fields are stored but not currently shown.

### Frontend-use labels

- `Displayed`: printed directly on listing cards, map items, map/detail pages, links, image galleries, or detail facts.
- `Tag`: converted into one of the short listing chips by `LetMeRent-FrontEnd/includes/listingTags.php`.
- `Filter/sort`: used by the Flask `/data` endpoint for frontend searching, filtering, pagination, or sorting.
- `Map`: used for Google Maps marker placement or detail map placement.
- `Fallback`: used only when the frontend has to build fallback text because a better field, usually `description`, is missing.
- `No`: stored in MongoDB but not currently displayed by the frontend.

### Shared fields

Most spiders try to provide these shared fields when the source site has the data.

| Field | Type | Meaning | Frontend |
|---|---|---|---|
| `url` | text | Original listing URL | Displayed as the detail-page source link; also used by map item data attributes |
| `source` | text | Spider name, added by the MongoDB pipeline | Displayed; filter by source |
| `title` | text | Listing title or street/address title | Displayed |
| `address` | text | Street address | Displayed |
| `street` | text | Street name or street address | Displayed; fallback description text |
| `city` | text | City name | Displayed; filter/sort by city |
| `price` | number | Monthly rent, stored without currency symbols | Displayed; filter/sort by budget |
| `living_area` | number | Living area in square meters | Tag; garage/parking filter checks for missing area |
| `rooms` | number | Number of rooms | Tag; filter by rooms |
| `property_type` | text | Property category/type | Tag; fallback description text |
| `availability` | text | Normalized move-in value (`Immediately` or `YYYY-MM-DD`) | Displayed; filter by move-in date |
| `status` | text | Normalized listing state (`Available`, `Rented`, etc.) | No |
| `description` | text | Listing description | Displayed |
| `images` | list | Listing photo URLs | Displayed on cards, map items, and detail gallery |
| `energy_label` | text | Energy grade | Tag; energy-label filter |
| `latitude` | number | Map latitude | Map |
| `longitude` | number | Map longitude | Map |
| `tags` | list | Source-side short descriptive tags | Fallback only; the frontend mostly rebuilds tags from individual fields |

### Pipeline fields added to every document

These fields are not scraped from listing websites. They are added by `LetMeRent.pipelines.MongoDBPipeline`.

| Field | Type | Meaning | Frontend |
|---|---|---|---|
| `source` | text | Spider name, for example `funda` | Displayed; filter by source |
| `scraped_at` | timestamp | When the listing was last scraped | Displayed; used for the card `NEW` badge |
| `created_at` | timestamp | When the listing was first inserted | Filter/sort; used for newest/old-listing logic |

The pipeline also removes old deprecated fields on update: `available_from`, `furnishing`, `home_type`, `image`, `lat`, `lng`, `price_suffix`, and `size`.

### funda

| Field | Type | Meaning | Frontend |
|---|---|---|---|
| `url` | text | Listing detail page URL | Displayed |
| `title` | text | Listing title, usually the street address | Displayed |
| `address` | text | Street address | Displayed |
| `city` | text | City parsed from postal/city line | Displayed; filter/sort |
| `street` | text | Street name/address | Displayed |
| `postal_city` | text | Postal code plus city line, for example `7811 AB Emmen` | No |
| `neighbourhood` | text | Neighbourhood name | Displayed; tag |
| `latitude` | number | Listing latitude | Map |
| `longitude` | number | Listing longitude | Map |
| `price` | number | Monthly rent | Displayed; filter/sort |
| `living_area` | number | Living area in square meters | Tag; filter |
| `plot_size` | number | Plot/lot area in square meters | Tag; filter |
| `rooms` | number | Number of bedrooms stored as rooms | Tag; filter |
| `bedrooms` | number | Number of bedrooms | Tag |
| `energy_label` | text | Energy grade | Tag; filter |
| `status` | text | Normalized listing status | No |
| `availability` | text | Normalized acceptance/move-in text | Displayed; filter |
| `description` | text | Listing description | Displayed |
| `agent_person` | text | Contact person name | No |
| `agent` | text | Estate agent name | Displayed on detail page as landlord/source contact fallback |
| `agent_url` | text | Estate agent page URL | No |
| `phone` | text | Contact phone number | No |
| `images` | list | Photo URLs | Displayed |
| `features` | dict | Detail-page feature table, label to value | Tag/filter for selected values such as bathrooms, construction year, and home type |
| `tags` | list | Source-side descriptive chips | Fallback only |

### housinganywhere

| Field | Type | Meaning | Frontend |
|---|---|---|---|
| `title` | text | Listing title from the result card | Displayed |
| `city` | text | City searched/scraped | Displayed; filter/sort |
| `price` | number | Monthly rent | Displayed; filter/sort |
| `price_label` | text | Price period label from the card | No |
| `living_area` | number | Living area in square meters | Tag; filter |
| `housemates` | number | Current occupancy / housemates | Tag; filter |
| `availability` | text | Normalized move-in date | Displayed; filter |
| `url` | text | Listing detail page URL | Displayed |
| `images` | list | Photo URLs | Displayed |
| `srcset_images` | list | Extra card image `srcset` values | No |
| `tenant_type` | text | Allowed tenant type, for example `Students only` | Tag; fallback description text |
| `status` | text | Normalized status derived from availability | No |
| `property_type` | text | Property kind/type | Tag; fallback description text |
| `floor` | number | Floor number | Tag; fallback description text |
| `furnished` | text | Furnishing value | Tag; filter/fallback |
| `deposit_policy` | text | Deposit rule, for example `No deposit` | Tag; fallback description text |
| `latitude` | number | Listing latitude | Map |
| `longitude` | number | Listing longitude | Map |
| `street` | text | Street address | Displayed; fallback description text |
| `description` | text | Listing description | Displayed |
| `rental_period` | text | Minimum stay text | Displayed in detail facts |
| `utilities` | text | Utility inclusion text, for example `Incl. utilities` | Tag |
| `garden` | text | Garden presence | Tag |
| `parking` | text | Parking presence | Tag |
| `wheelchair_accessible` | text | Wheelchair accessibility | Tag |
| `kitchen` | text | Kitchen type (`Shared`, `Private`) | Tag |
| `bathroom` | text | Bathroom type (`Shared`, `Private`) | Tag |
| `toilet` | text | Toilet type (`Shared`, `Private`) | Tag |
| `energy_label` | text | Energy label from facilities, usually empty | Tag; filter |
| `facilities` | list | Facility/amenity names | Fallback description text |
| `tags` | list | Not currently yielded by this spider | Fallback only if present |

### huurwoningen

| Field | Type | Meaning | Frontend |
|---|---|---|---|
| `url` | text | Listing detail page URL | Displayed |
| `title` | text | Listing title | Displayed |
| `address` | text | Street address | Displayed |
| `price` | number | Monthly rent | Displayed; filter/sort |
| `living_area` | number | Living/surface area in square meters | Tag; filter |
| `rooms` | number | Number of rooms | Tag; filter |
| `city` | text | City searched/scraped | Displayed; filter/sort |
| `postal_code` | text | Postal code from the listing summary | No |
| `latitude` | number | Latitude derived from postal code | Map |
| `longitude` | number | Longitude derived from postal code | Map |
| `interior` | text | Furnishing/interior state | Tag; filter/fallback |
| `description` | text | Listing description | Displayed |
| `images` | list | Card and detail photo URLs | Displayed |
| `energy_label` | text | Energy grade | Tag; filter |
| `property_type` | text | Dwelling type | Tag; fallback description text |
| `property_types` | text | Property type | Tag |
| `construction_type` | text | Construction type | Stored in source-side `tags`; otherwise no direct frontend use |
| `construction_year` | number | Year built | Tag |
| `bathrooms` | number | Number of bathrooms | Tag |
| `floors` | number | Number of floors | Tag |
| `floor` | number | Storey number | Tag; fallback description text |
| `housemates` | number | Number of roommates | Tag; filter/fallback |
| `gender_of_housemates` | text | Preferred/mixed housemate gender | Tag |
| `kitchen` | text | Kitchen value | Tag |
| `bathroom` | text | Bathroom value | Tag |
| `toilet` | text | Toilet value | Tag |
| `situation` | text | Location/situation value | Tag |
| `balcony` | text | Balcony presence | Tag |
| `roof_terrace` | text | Roof terrace presence | Tag |
| `garden` | text | Garden presence | Tag |
| `storage` | text | Storage presence | Tag |
| `parking` | text | Parking presence | Tag |
| `garage` | text | Garage presence | Tag |
| `status` | text | Normalized listing status | No |
| `offered_since` | text | Date the listing was offered | No |
| `availability` | text | Normalized move-in value | Displayed; filter |
| `upkeep` | text | State of maintenance | Tag |
| `rental_period` | text | Lease length text | Displayed in detail facts |
| `deposit` | number | Deposit amount | Tag |
| `smoking_allowed` | text | Smoking permission | Tag |
| `pets_allowed` | text | Pet permission | Tag |
| `target_audience` | text | Required renter status/audience | Tag |
| `utilities` | number/text | Utility prepayment total | Tag |
| `tags` | list | Source-side descriptive chips | Fallback only |

### irentalize

| Field | Type | Meaning | Frontend |
|---|---|---|---|
| `city_filter` | text | City selected in the iRentalize filter | No |
| `listing_page` | number | Result page where the listing was found | No |
| `url` | text | Property detail page URL | Displayed |
| `title` | text | Listing title/address | Displayed |
| `property_type` | text | Property type from the page heading | Tag; fallback description text |
| `city` | text | City extracted from page text/headings | Displayed; filter/sort |
| `latitude` | number | Latitude derived from address lookup | Map |
| `longitude` | number | Longitude derived from address lookup | Map |
| `living_area` | number | Living area in square meters | Tag; filter |
| `rooms` | number | Number of rooms | Tag; filter |
| `housemates` | number | Assumed housemates (`rooms - 1`) | Tag; filter/fallback |
| `bathrooms` | number | Number of bathrooms | Tag |
| `kitchens` | number | Number of kitchens | Tag |
| `toilets` | number | Number of toilets | Tag |
| `floors` | number | Number of floors | Tag |
| `availability` | text | Normalized move-in value | Displayed; filter |
| `status` | text | Normalized status | No |
| `price` | number | Monthly rent, using base rent or starting price | Displayed; filter/sort |
| `starting_price` | number | Starting-from price | No |
| `base_rent` | number | Base rent | No |
| `service_fee` | number | Service fee | Tag |
| `utilities` | number | Utilities amount | Tag |
| `furnished` | text | Furnishing value | Tag; filter/fallback |
| `energy_label` | text | Energy grade | Tag; filter |
| `tags` | list | Feature labels not mapped to specific fields | Fallback only |
| `images` | list | Photo URLs, with site logo removed | Displayed |
| `description` | text | Listing description | Displayed |
| `landlord_name` | text | Landlord/author name | No; detail page currently looks for `landlord`, `agent`, or `contact_name`, not this field |

### kamernet

| Field | Type | Meaning | Frontend |
|---|---|---|---|
| `url` | text | Listing detail page URL | Displayed |
| `title` | text | Listing title/street | Displayed |
| `images` | list | Photo URLs | Displayed |
| `address` | text | Street address | Displayed |
| `street` | text | Street name/address | Displayed; fallback description text |
| `city` | text | City name | Displayed; filter/sort |
| `living_area` | number | Living area in square meters | Tag; filter |
| `furnished` | text | Furnishing text | Tag; filter/fallback |
| `property_type` | text | Property type | Tag; fallback description text |
| `availability` | text | Normalized move-in date | Displayed; filter |
| `price` | number | Monthly rent | Displayed; filter/sort |
| `price_label` | text | Price period / utilities label | Used internally by spider to derive `utilities`; not displayed |
| `latitude` | number | Listing latitude | Map |
| `longitude` | number | Listing longitude | Map |
| `status` | text | Always `Available` for scraped Kamernet listings | No |
| `description` | text | Listing description | Displayed |
| `amenities` | list | Raw `What you'll get` amenities | No; selected amenities are split into fields/tags |
| `tags` | list | Remaining amenity/furnished/type/rental-period tags | Fallback only |
| `energy_label` | text | Energy grade | Tag; filter |
| `housemates` | number | Number of roommates | Tag; filter/fallback |
| `gender_of_housemates` | text | Gender mix/preference | Tag |
| `kitchen` | text | Kitchen type | Tag |
| `bathroom` | text | Bathroom type | Tag |
| `toilet` | text | Toilet type | Tag |
| `pets_allowed` | text | Pet permission | Tag |
| `smoking_allowed` | text | Smoking permission | Tag |
| `utilities` | number/text | Additional monthly utilities or inclusion text | Tag |
| `deposit` | number | Deposit amount | Tag |
| `rental_period` | text | Rental period text | Displayed in detail facts; tag |
| `duration_of_stay` | text | Ideal tenant duration of stay | Displayed in detail facts before `rental_period` |
| `ideal_tenant` | dict | Ideal tenant rows such as occupation, gender, age, number of tenants | Tag for occupation/gender only |
| `landlord_name` | text | Landlord name | No; detail page currently looks for `landlord`, `agent`, or `contact_name`, not this field |
| `landlord_type` | text | Landlord type/status | No |
| `posted` | text | Posted text from Kamernet header | No |

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
