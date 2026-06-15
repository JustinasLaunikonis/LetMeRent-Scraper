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
        # Step 1: read the search results page
        # Each card gives us basics, but useful tags (like "No deposit").
        # Follow the link to the detail page, where parse_detail() collects the rest
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
        # Step 2: read the listings detail page and add the extra fields
        # "listing" is the same as built in parse() but we keep adding to it
        listing = basics

        # "No deposit", "Furnished", "Private room in house", "5 housemates (mixed)", "Floor: 2".
        # We collect them all into a "tags" list so the frontend can show them
        tags = []
        deposit_policy = None
        property_kind = None
        furnished = None
        floor = None

        highlight_nodes = response.css('[data-test-locator^="HighlightsTags/"]')
        for node in highlight_nodes:
            label = clean_text(node.css("::text").getall())
            if label == "":
                continue

            tags.append(label)

            # Work out which kind of tag this is from its locator name
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
        if street is not None:
            street = street.strip()

        # The map location (latitude/longitude) comes from the JSON-LD on the page.
        latitude, longitude = get_coordinates(response)

        # Price on the detail page
        # If the detail page shows a price, use it instead of the card price.
        detail_price = response.css('[data-test-locator="Listing/ListingInfo/Price"]::text').get()
        detail_price_number = extract_number(detail_price)
        if detail_price_number is not None:
            listing["price"] = detail_price_number

        description = clean_text(
            response.css('[data-test-locator="Listing/ListingDescription"]::text').getall()
        )

        # The word "Description" is the section heading, drop it if it is there.
        if description.startswith("Description"):
            description = description[len("Description"):].strip()

        # Facilities and amenities (a list of names)
        facilities = []
        facility_texts = response.css(
            '[data-test-locator="ListingDetailedInfosSection/TwoColumnsContainer/facilities"] ::text'
        ).getall()
        for facility_text in facility_texts:
            name = facility_text.strip()
            if name != "":
                facilities.append(name)
                if name not in tags:
                    tags.append(name)

        # Tenant rules and preferences
        # "Tenant type: Students only" drop the label so only the value is left
        tenant_type_raw = clean_text(
            response.css('[data-test-locator="Preferences/TenantType"] ::text').getall()
        )
        tenant_type = remove_label(tenant_type_raw, "Tenant type:")

        tenant_age_raw = clean_text(
            response.css('[data-test-locator="Preferences/TenantAge"] ::text').getall()
        )
        tenant_age = remove_label(tenant_age_raw, "Age:")

        tenant_gender_raw = clean_text(
            response.css('[data-test-locator="Preferences/TenantGender"] ::text').getall()
        )
        tenant_gender = remove_label(tenant_gender_raw, "Gender:")

        detail_images = detail_page_images(response)
        if detail_images:
            listing["images"] = detail_images

        # Add all the extra detail page fields to the item
        listing["street"] = street
        listing["latitude"] = latitude
        listing["longitude"] = longitude
        listing["tags"] = tags
        listing["deposit_policy"] = deposit_policy
        listing["property_type"] = property_kind
        listing["furnished"] = furnished
        listing["floor"] = floor
        listing["description"] = description
        listing["facilities"] = facilities
        listing["tenant_type"] = tenant_type
        listing["tenant_age"] = tenant_age
        listing["tenant_gender"] = tenant_gender

        # The card text looks like "Available from 1 September" or "Available now".
        # read the status from the full text ("Available", "Rented", ...) then remove the label "Available from"
        listing["status"] = normalize_status(listing.get("availability"))
        move_in_text = remove_label(listing.get("availability"), "Available from")
        # Turn the move-in text into the universal format, for example "1 September" -> "2026-09-01".
        listing["availability"] = normalize_availability(move_in_text)

        # HousingAnywhere has no energy label, but keep the field (empty)
        listing["energy_label"] = ""

        yield listing
