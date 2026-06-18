import scrapy
import re
import json

from LetMeRent.spiders.city_utils import city_title, housinganywhere_city, normalize_status, normalize_availability


def extract_number(text):
    # Keep only the digits from the text, so "€850" becomes 850
    # Returns None when there is no number at all
    if text is None:
        return None

    digits_only = re.sub(r"[^\d]", "", text)

    if digits_only == "":
        return None

    return int(digits_only)


def remove_label(text, label):
    # Remove label from the text, so a value like
    # "Tenant type: Students only" becomes just "Students only"
    if text is None:
        return None

    cleaned = text.strip()
    if cleaned.startswith(label):
        cleaned = cleaned[len(label):]

    return cleaned.strip()


def to_number(text):
    # Turn a coordinate like "52.7912574" into a float
    if text is None:
        return None

    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def get_coordinates(response):
    # HousingAnywhere puts the exact map location in a JSON-LD script on the detail page
    # read thelatitude and longitude from there so the listing can show on the map
    json_blocks = response.css('script[type="application/ld+json"]::text').getall()

    for block in json_blocks:
        try:
            data = json.loads(block)
        except ValueError:
            continue

        # only need the "geo" part with the coordinates
        if not isinstance(data, dict):
            continue

        geo = data.get("geo")
        if not isinstance(geo, dict):
            continue

        latitude = to_number(geo.get("latitude"))
        longitude = to_number(geo.get("longitude"))
        if latitude is not None and longitude is not None:
            return latitude, longitude

    # No coordinates found on this page, return none
    return None, None


def full_quality_image(image_url):
    # https://housinganywhere.imgix.net/unit_type/1654245/<id>.jpg?ixlib=...&w=120&h=90&q=20
    if not image_url:
        return ""

    if "imgix" not in image_url:
        return image_url

    # Everything before "?" is the original image path.
    return image_url.split("?", 1)[0]


def detail_page_images(response):
    # The detail page shows the full photo gallery: a big image slider plus a row of preview tiles.
    slider_srcs = response.css(
        '[data-test-locator^="Listing/ImageSlider/"] img::attr(src)'
    ).getall()
    tile_srcs = response.css(
        '[data-test-locator^="Photo button"] img::attr(src)'
    ).getall()

    images = []
    for raw in slider_srcs + tile_srcs:
        image = full_quality_image(raw)
        if image and image not in images:
            images.append(image)

    return images


def clean_text(parts):
    # Join a list of text pieces into one clean string
    pieces = []
    for part in parts:
        piece = part.strip()
        if piece != "":
            pieces.append(piece)

    return " ".join(pieces)


def extract_balanced_object(text, start):
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        else:
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start:index + 1]
    return None


def preloaded_state(response):
    for script in response.css("script::text").getall():
        if "__PRELOADED_STATE__" not in script:
            continue
        marker = script.find("__PRELOADED_STATE__")
        brace = script.find("{", marker)
        if brace == -1:
            continue
        block = extract_balanced_object(script, brace)
        if not block:
            continue
        try:
            return json.loads(block)
        except ValueError:
            continue
    return None


def facility_value(facilities, key):
    # Read one facility as clean lower-case text ("Yes" -> "yes", missing -> "").
    if not isinstance(facilities, dict):
        return ""
    value = facilities.get(key)
    if value is None:
        return ""
    return str(value).strip().lower()


def facility_present(facilities, key, *accepted):
    # True when a facility is present.
    value = facility_value(facilities, key)
    if value == "":
        return False
    if accepted:
        return value in accepted
    return value == "yes"


def shared_or_private(value):
    # Turn a facility value into the qualifier the frontend prints in front of
    # "kitchen"/"bathroom"/"toilet", e.g. "shared" -> "Shared"
    if value == "shared":
        return "Shared"
    if value in ("private", "own", "yes"):
        return "Private"
    return ""


def collect_facilities(facilities):
    names = []

    def add(name):
        if name and name not in names:
            names.append(name)

    if facility_present(facilities, "wifi"):
        add("WiFi")
    if facility_present(facilities, "internet_included"):
        add("Internet included")
    if facility_present(facilities, "washing_machine"):
        add("Washing machine")
    if facility_present(facilities, "dryer"):
        add("Dryer")
    if facility_present(facilities, "dishwasher"):
        add("Dishwasher")
    if facility_present(facilities, "tv"):
        add("TV")
    if facility_present(facilities, "desk"):
        add("Desk")
    if facility_present(facilities, "closet"):
        add("Wardrobe")
    if facility_present(facilities, "bed"):
        add("Bed")
    if facility_present(facilities, "elevator"):
        add("Elevator")
    if facility_present(facilities, "allergy_friendly"):
        add("Allergy friendly")
    if facility_value(facilities, "heating") == "central":
        add("Central heating")

    kitchen = facility_value(facilities, "kitchen")
    if kitchen == "shared":
        add("Shared kitchen")
    elif kitchen in ("private", "own", "yes"):
        add("Private kitchen")

    toilet = facility_value(facilities, "toilet")
    if toilet == "shared":
        add("Shared toilet")
    elif toilet in ("private", "own", "yes"):
        add("Private toilet")

    flooring = facility_value(facilities, "flooring")
    if flooring not in ("", "no", "none"):
        add(flooring.capitalize() + " flooring")

    return names


def bills_included(costs):
    # The "costs" block marks each utility as "included-in-rent" or not.
    if not isinstance(costs, dict):
        return False
    inner = costs.get("costs")
    if not isinstance(inner, dict):
        return False
    for detail in inner.values():
        if isinstance(detail, dict) and detail.get("payableBy") == "included-in-rent":
            return True
    return False


class HousinganywhereSpider(scrapy.Spider):
    name = "housinganywhere"
    allowed_domains = ["housinganywhere.com"]
    start_urls = ["https://housinganywhere.com/s/"]

    def __init__(self, city=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.city = housinganywhere_city(city)
        self.city_name = city_title(city)

    def start_requests(self):
        url = f"https://housinganywhere.com/s/{self.city}"
        yield scrapy.Request(url=url, callback=self.parse)

    def parse(self, response):
        cards = response.css('[data-test-locator="ListingCard/Anchor"]')

        for card in cards:
            title = card.css('[data-test-locator="ListingCard/Title"]::text').get()
            price = card.css('[data-test-locator="ListingCard/Price"]::text').get()
            price_label = card.css('[data-test-locator="ListingCard/PriceLabel"]::text').get()
            size = card.css('[data-test-locator="ListingCard/AttributesSize"] span::text').get()
            housemates = card.css('[data-test-locator="ListingCard/AttributesPlaces"] span::text').get()
            # The availability has two parts: a label "Available from " and
            # the date in a second span (for example "1 September").
            # parse_detail turns this into the status and the move-in date
            availability_parts = card.css('[data-test-locator="ListingCard/Availability"] span::text').getall()
            availability = clean_text(availability_parts)
            href = card.css("::attr(href)").get()

            images = card.css('[data-test-locator="ListingCardPhotoGallery/Photo"]::attr(src)').getall()

            # some images are only given as a "srcset" instead of "src".
            srcset_images = card.css('[data-test-locator="ListingCardPhotoGallery/Photo"]::attr(srcset)').getall()

            if not href:
                continue

            detail_url = response.urljoin(href)

            # Save the basics we already have.
            # We pass this to parse_detail(), which adds the extra fields
            # Prices and sizes are stored as plain numbers (no "€" or "m²").
            basics = {
                "title": title,
                "city": self.city_name,
                "price": extract_number(price),
                "price_label": price_label,
                "living_area": extract_number(size),
                "housemates": extract_number(housemates),
                "availability": availability,
                "url": detail_url,
                "images": images,
                "srcset_images": srcset_images,
            }

            # Open the listings own page
            yield scrapy.Request(
                url=detail_url,
                callback=self.parse_detail,
                cb_kwargs={"basics": basics},
            )

    def parse_detail(self, response, basics):
        listing = basics

        entity = None
        state = preloaded_state(response)
        if isinstance(state, dict):
            listing_state = state.get("listing")
            if isinstance(listing_state, dict):
                candidate = listing_state.get("entity")
                if isinstance(candidate, dict):
                    entity = candidate

        if entity is not None:
            self.fill_from_state(listing, entity, response)
        else:
            self.fill_from_html(listing, response)

        tenant_type_raw = clean_text(
            response.css('[data-test-locator="Preferences/TenantType"] ::text').getall()
        )
        tenant_type = remove_label(tenant_type_raw, "Tenant type:")
        if tenant_type:
            listing["tenant_type"] = tenant_type

        # The card text looks like "Available from 1 September" or "Available now".
        # Read the status ("Available", "Rented", ...) then drop the label and turn
        # the move-in text into the universal format ("1 September" -> "2026-09-01").
        listing["status"] = normalize_status(listing.get("availability"))
        move_in_text = remove_label(listing.get("availability"), "Available from")
        listing["availability"] = normalize_availability(move_in_text)

        yield listing

    def fill_from_state(self, listing, entity, response):
        facilities = entity.get("facilities")
        if not isinstance(facilities, dict):
            facilities = {}

        # The JSON gives the price in cents (57500) store it in euros (575).
        price = entity.get("price")
        if isinstance(price, (int, float)) and price > 0:
            listing["price"] = round(price / 100)

        property_type = (entity.get("unitTypeType") or entity.get("kindLabel") or "").strip()
        if property_type:
            listing["property_type"] = property_type[:1].upper() + property_type[1:]

        living_area = facility_value(facilities, "bedroom_size") or facility_value(facilities, "total_size")
        living_area_number = extract_number(living_area)
        if living_area_number is not None:
            listing["living_area"] = living_area_number

        occupancy = entity.get("currentOccupancy")
        if isinstance(occupancy, int) and occupancy > 0:
            listing["housemates"] = occupancy

        units = entity.get("units")
        if isinstance(units, list) and units and isinstance(units[0], dict):
            floor = units[0].get("floor")
            if isinstance(floor, int):
                listing["floor"] = floor

        if facility_present(facilities, "bedroom_furnished"):
            listing["furnished"] = "Furnished"

        deposit_policy = (entity.get("depositPolicyLabel") or "").strip()
        if deposit_policy and deposit_policy.lower() != "classical deposit":
            listing["deposit_policy"] = deposit_policy.capitalize()

        latitude = to_number(entity.get("latitude"))
        longitude = to_number(entity.get("longitude"))
        if latitude is not None and longitude is not None:
            listing["latitude"] = latitude
            listing["longitude"] = longitude

        street = (entity.get("street") or "").strip()
        if street:
            listing["street"] = street

        description = (entity.get("description") or "").strip()
        if description:
            listing["description"] = description
        minimum_stay = entity.get("minimumStayMonths")
        if isinstance(minimum_stay, int) and minimum_stay > 0:
            if minimum_stay == 1:
                listing["rental_period"] = "1 month minimum"
            else:
                listing["rental_period"] = f"{minimum_stay} months minimum"

        if bills_included(entity.get("costs")):
            listing["utilities"] = "Incl. utilities"

        if facility_present(facilities, "garden", "yes", "shared", "private", "own"):
            listing["garden"] = "Present"

        if facility_present(facilities, "parking", "yes", "shared", "private", "free", "paid"):
            listing["parking"] = "Yes"

        if facility_present(facilities, "wheelchair_accessible"):
            listing["wheelchair_accessible"] = "Yes"

        kitchen = shared_or_private(facility_value(facilities, "kitchen"))
        if kitchen:
            listing["kitchen"] = kitchen
        bathroom = shared_or_private(facility_value(facilities, "bathroom"))
        if bathroom:
            listing["bathroom"] = bathroom
        toilet = shared_or_private(facility_value(facilities, "toilet"))
        if toilet:
            listing["toilet"] = toilet

        listing["energy_label"] = facility_value(facilities, "energy_label").upper()

        listing["facilities"] = collect_facilities(facilities)

        images = []
        for photo in entity.get("photoURLList") or []:
            if isinstance(photo, dict):
                image = full_quality_image(photo.get("url"))
                if image and image not in images:
                    images.append(image)
        if not images:
            images = detail_page_images(response)
        if images:
            listing["images"] = images

    def fill_from_html(self, listing, response):
        # Fallback for when the embedded JSON is missing: read the visible page.
        deposit_policy = None
        property_kind = None
        furnished = None
        floor = None

        highlight_nodes = response.css('[data-test-locator^="HighlightsTags/"]')
        for node in highlight_nodes:
            label = clean_text(node.css("::text").getall())
            if label == "":
                continue

            # Work out which kind of tag this is from its locator name,
            # for example "HighlightsTags/DepositPolicy".
            locator = node.attrib.get("data-test-locator", "")
            if locator.endswith("/DepositPolicy"):
                deposit_policy = label
            elif locator.endswith("/Kind"):
                property_kind = label
            elif locator.endswith("/Furnished"):
                furnished = label
            elif locator.endswith("/FloorNumber"):
                # The chip reads like "Floor: 2", we only want the number.
                floor = extract_number(label)

        street = response.css('[data-test-locator="Listing/ListingInfo/street"]::text').get()
        if street is not None and street.strip():
            listing["street"] = street.strip()

        # The map location (latitude/longitude) comes from the JSON-LD on the page.
        latitude, longitude = get_coordinates(response)
        if latitude is not None and longitude is not None:
            listing["latitude"] = latitude
            listing["longitude"] = longitude

        # If the detail page shows a price, use it instead of the card price.
        detail_price = response.css('[data-test-locator="Listing/ListingInfo/Price"]::text').get()
        detail_price_number = extract_number(detail_price)
        if detail_price_number is not None:
            listing["price"] = detail_price_number

        description_parts = response.css('[data-test-locator="LongParagraph"]::text').getall()
        if not description_parts:
            description_parts = response.xpath(
                '//*[normalize-space()="Description"]/following-sibling::p[1]//text()'
            ).getall()
        if not description_parts:
            description_parts = response.css(
                '[data-test-locator="Listing/ListingDescription"]::text'
            ).getall()

        description = clean_text(description_parts)
        # The word "Description" is the section heading, drop it if it is there.
        if description.startswith("Description"):
            description = description[len("Description"):].strip()
        if description:
            listing["description"] = description

        # Facilities and amenities. Only keep the AVAILABLE ones: the page also
        # lists unavailable facilities struck-through as "No ..." (e.g. "No Parking").
        facilities = []
        facility_texts = response.css(
            '[data-test-locator="ListingDetailedInfosSection/TwoColumnsContainer/facilities"] ::text'
        ).getall()
        for facility_text in facility_texts:
            name = facility_text.strip()
            if not name or name in facilities:
                continue
            if name.lower().startswith("no "):
                continue
            facilities.append(name)
        listing["facilities"] = facilities

        detail_images = detail_page_images(response)
        if detail_images:
            listing["images"] = detail_images

        if deposit_policy and deposit_policy.lower() != "classical deposit":
            listing["deposit_policy"] = deposit_policy
        if property_kind:
            listing["property_type"] = property_kind
        if furnished:
            listing["furnished"] = furnished
        if floor is not None:
            listing["floor"] = floor

        # HousingAnywhere has no energy label, but keep the field (empty)
        listing["energy_label"] = ""
