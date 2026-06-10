import re
import scrapy

from LetMeRent.spiders.city_utils import city_slug, city_title, normalize_status


def extract_number(text):
    # Keep only the digits from the text, so "66 m²" becomes 66
    # Returns None when there is no number at all
    if text is None:
        return None

    digits_only = re.sub(r"[^\d]", "", text)

    if digits_only == "":
        return None

    return int(digits_only)


def clean_text(parts):
    # Join a list of text pieces into one clean string
    pieces = []
    for part in parts:
        piece = part.strip()
        if piece != "":
            pieces.append(piece)

    return " ".join(pieces)


def feature_value(response, modifier):
    # Read one feature value from the details box,
    # for example "balcony" or "number_of_bathrooms".
    # its in a span with the class "listing-features__main-description"
    selector = ".listing-features__description--" + modifier + " .listing-features__main-description::text"
    value = response.css(selector).get()
    if value is None:
        return ""
    return value.strip()


class HuurwoningenSpider(scrapy.Spider):
    name = "huurwoningen"
    allowed_domains = ["huurwoningen.nl"]

    def __init__(self, city=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.city_name = city_title(city)
        self.city = city_slug(city)

    async def start(self):
        url = f"https://www.huurwoningen.nl/en/in/{self.city}"
        yield scrapy.Request(url=url, callback=self.parse)

    def parse(self, response):
        cards = response.css("section.listing-search-item")

        for card in cards:
            # Title of the listing
            title = card.css(".listing-search-item__link--title::text").get("")
            title = title.strip()

            # The sub-title holds the address.
            # It sometimes has extra text in brackets, so we cut everything from the first "(" onwards.
            raw_address = card.css(".listing-search-item__sub-title::text").get("")
            raw_address = raw_address.strip()
            address = raw_address.split("(")[0]
            address = address.strip()

            # Price is a number, store it without the "€" or "per month" text
            raw_price = card.css(".listing-search-item__price-main::text").get("")
            price = extract_number(raw_price)

            # Surface area is a number, store it without the "m²"
            raw_size = card.css(".illustrated-features__item--surface-area::text").get("")
            living_area = extract_number(raw_size)

            # Number of rooms is a number
            raw_rooms = card.css(".illustrated-features__item--number-of-rooms::text").get("")
            rooms = extract_number(raw_rooms)

            # Link to the detail page and the first image on the card
            href = card.css(".listing-search-item__link--title::attr(href)").get()
            image = card.css(".picture__image::attr(src)").get()

            images = []
            if image:
                images.append(image)

            # Only follow the listing if theres a link
            if href:
                yield response.follow(
                    href,
                    callback=self.parse_detail,
                    cb_kwargs={
                        "title": title,
                        "address": address,
                        "price": price,
                        "living_area": living_area,
                        "rooms": rooms,
                        "images": images,
                        "url": response.urljoin(href),
                    },
                )

        # Go to the next results page if there is one
        next_page = response.css(".pagination__item--next a::attr(href)").get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)

    def parse_detail(self, response, **kwargs):
        # Some listings do not show a price on the search card (for example "price transparency" listings).
        # In that case the price is still on the detail page, so read it from the summary box as a fallback.
        price = kwargs.get("price")
        if price is None:
            raw_price = response.css(".listing-detail-summary__price-main::text").get("")
            price = extract_number(raw_price)
            kwargs["price"] = price

        # description text is built by stripping each piece and dropping the
        # empty ones, then joining what is left with single spaces.
        description_parts = response.css(".listing-detail-description__truncated::text").getall()
        description_pieces = []
        for part in description_parts:
            piece = part.strip()
            if piece != "":
                description_pieces.append(piece)
        description = " ".join(description_pieces)

        # Collect all the images
        card_images = kwargs.pop("images", [])
        detail_images = response.css(".carrousel__item .picture__image::attr(src)").getall()

        images = []
        for image in card_images:
            if image not in images:
                images.append(image)
        for image in detail_images:
            if image not in images:
                images.append(image)

        # Furnishing / interior condition (may be empty on some listings)
        interior = response.css("[aria-describedby='tooltip-listing-features-interior']::text").get("")
        interior = interior.strip()

        # Energy rating
        energy_label = response.css("[class*='listing-features__description--energy-label'] .listing-features__main-description::text").get("")
        energy_label = energy_label.strip()

        # Physical features
        property_type = feature_value(response, "dwelling_type")
        property_types = feature_value(response, "property_types")
        construction_type = feature_value(response, "construction_type")
        balcony = feature_value(response, "balcony")
        roof_terrace = feature_value(response, "roof_terrace")

        # Numeric features
        construction_year = extract_number(feature_value(response, "construction_period"))
        bathrooms = extract_number(feature_value(response, "number_of_bathrooms"))
        floors = extract_number(feature_value(response, "number_of_floors"))

        # The "transfer" rows (Status, Available, etc.)
        feature_terms = response.css(".listing-features__term")
        feature_descriptions = response.css(".listing-features__description")
        labelled_features = {}

        # Only check rows that have both a label and a value
        pair_count = min(len(feature_terms), len(feature_descriptions))
        for i in range(pair_count):
            label = clean_text(feature_terms[i].css("::text").getall())
            value = clean_text(feature_descriptions[i].css("::text").getall())
            if label != "" and label not in labelled_features:
                labelled_features[label] = value

        # Status comes as text like "For rent" so turn it into a standard word
        raw_status = labelled_features.get("Status", "")
        status = normalize_status(raw_status)
        offered_since = labelled_features.get("Offered since", "")
        # availability is the move-in text. example: "Immediately".
        availability = labelled_features.get("Available", "")
        upkeep = labelled_features.get("Upkeep", "")

        tags = []

        # Descriptive features that are useful as tags
        descriptive = [property_type, property_types, interior, construction_type]
        for value in descriptive:
            if value != "" and value not in tags:
                tags.append(value)

        # Balcony and roof terrace only make sense as tags when present
        if balcony == "Present":
            tags.append("Balcony")
        if roof_terrace == "Present":
            tags.append("Roof terrace")

        listing = {}
        for key in kwargs:
            listing[key] = kwargs[key]

        listing["city"] = self.city_name
        listing["interior"] = interior
        listing["description"] = description
        listing["images"] = images
        listing["energy_label"] = energy_label
        listing["property_type"] = property_type
        listing["property_types"] = property_types
        listing["construction_type"] = construction_type
        listing["construction_year"] = construction_year
        listing["bathrooms"] = bathrooms
        listing["floors"] = floors
        listing["balcony"] = balcony
        listing["roof_terrace"] = roof_terrace
        listing["status"] = status
        listing["offered_since"] = offered_since
        listing["availability"] = availability
        listing["upkeep"] = upkeep
        listing["tags"] = tags

        yield listing
