import scrapy
import re
import json
from urllib.parse import urlparse, parse_qs, unquote

from LetMeRent.spiders.city_utils import city_slug, normalize_availability


def full_size_image(image_url):
    # Kamernet shows photos through Next.js image optimizer, which gives a small low quality thumbnail.
    # The URL looks like: /_next/image?url=https%3A%2F%2Fresources.kamernet.nl%2Fimage%2F<id>&w=640&q=75
    # The original full-quality photo is the "url" value inside that link,
    # so we can pull it out and use that instead.
    # Other URLs are returned unchanged.
    if image_url is None:
        return ""

    if "/_next/image" not in image_url:
        return image_url

    # Read the query part of the URL and look for the "url" parameter
    query_part = urlparse(image_url).query
    query_values = parse_qs(query_part)

    if "url" in query_values:
        original = query_values["url"][0]
        return unquote(original)

    return image_url


def detail_page_images(response):
    # The detail page loads its photo gallery with JavaScript, so the HTML we
    # download only contains a low-quality thumbnail. Luckily Kamernet is a
    # Next.js site, which means the full data is also written into a JSON blob
    # inside a <script id="__NEXT_DATA__"> tag. That JSON has a list of photo
    # ids ("imageList"), and each id maps to a full-quality photo at
    # https://resources.kamernet.nl/image/<id>.
    # This function reads that list and returns the full-quality photo URLs.
    # Returns an empty list when the data is missing or cannot be read.
    raw_json = response.css("script#__NEXT_DATA__::text").get()
    if not raw_json:
        return []

    # Turn the text into a Python object. If it is broken, give up safely.
    try:
        data = json.loads(raw_json)
    except ValueError:
        return []

    # Walk down the JSON step by step. At each step, stop if the key is missing.
    page_props = data.get("props", {}).get("pageProps", {})
    target = page_props.get("targetPageProps", {})
    listing_details = target.get("listingDetails", {})
    image_ids = listing_details.get("imageList", [])

    # Build the full-quality URL for every photo id we found.
    image_urls = []
    for image_id in image_ids:
        if image_id:
            image_urls.append("https://resources.kamernet.nl/image/" + image_id)

    return image_urls


def to_number(value):
    # Turn a coordinate like 52.78352 (or the text "52.78352") into a float.
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def detail_page_coordinates(response):
    # Kamernet draws a map on the detail page, and the location for it is written
    # into the same __NEXT_DATA__ JSON blob we already read for the photos

    raw_json = response.css("script#__NEXT_DATA__::text").get()
    if not raw_json:
        return None, None

    try:
        data = json.loads(raw_json)
    except ValueError:
        return None, None

    page_props = data.get("props", {}).get("pageProps", {})
    target = page_props.get("targetPageProps", {})
    listing_details = target.get("listingDetails", {})

    latitude = to_number(listing_details.get("postalCodeLat"))
    longitude = to_number(listing_details.get("postalCodeLong"))

    return latitude, longitude


def extract_number(text):
    # Keep only the digits from the text, so "€ 375" becomes 375
    # Returns None when there is no number at all
    if text is None:
        return None

    digits_only = re.sub(r"[^\d]", "", text)

    if digits_only == "":
        return None

    return int(digits_only)


class KamernetSpider(scrapy.Spider):
    name = "kamernet"
    allowed_domains = ["kamernet.nl"]

    def __init__(self, city=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.city = city_slug(city)
        self.start_urls = [f"https://kamernet.nl/en/for-rent/properties-{self.city}"]

    def parse(self, response, page=1, **kwargs):
        # Each search result is one clickable card
        cards = response.css("a.SearchResultCard_root__hSxn3")

        for card in cards:
            # The link to the detail page
            href = card.attrib.get("href", "")
            if href:
                url = "https://kamernet.nl" + href
            else:
                url = ""

            # First image shown on the card.
            # Upgrade it from the small thumbnail to the original full-quality photo.
            image = card.css("img::attr(src)").get("")
            image = full_size_image(image)

            # Street/address text.
            # It can contain a comma, so we remove it comma
            street = card.css(".SearchResultCard_contentRow__VZIJY span.CommonStyles_whiteSpaceNoWrap__wYjK1::text").get("")
            street = street.replace(",", "")
            street = street.strip()

            city = card.css(".SearchResultCard_contentRow__VZIJY span.MuiTypography-noWrap::text").get("")
            city = city.strip()

            # The second content row holds size, furnished, and property type, in that order.
            # Some cards do not have all three, so we check how many pieces there are before reading each one
            details = card.css(".SearchResultCard_contentRow__VZIJY + .SearchResultCard_contentRow__VZIJY p::text").getall()

            size_raw = ""
            if len(details) > 0:
                size_raw = details[0].strip()
            # Surface area is a number, store it as a plain number (not "m²")
            living_area = extract_number(size_raw)

            furnished = ""
            if len(details) > 1:
                furnished = details[1].strip()

            property_type = ""
            if len(details) > 2:
                property_type = details[2].strip()

            # The move-in date is shown as text like "From 1 July".
            # We look through the card lines for the one that starts with "From" and keep just the date part
            available_from_raw = card.css(".SearchResultCard_contentRow__VZIJY p::text").getall()
            availability = ""
            for line in available_from_raw:
                line = line.strip()
                if "From" in line:
                    # Drop the word "From" and keep the date.
                    availability = line.removeprefix("From").strip()
                    break

            # Turn the date into the universal format, for example "1 sep 2026" -> "2026-09-01"
            availability = normalize_availability(availability)

            # Price is a number, store it as a plain number (no "€")
            raw_price = card.css("span.MuiTypography-h5::text").get("")
            raw_price = raw_price.strip()
            price = extract_number(raw_price)

            price_type = card.css(".SearchResultCard_contentRow__VZIJY p.MuiTypography-body2::text").getall()
            price_label = ""
            for line in price_type:
                line = line.strip()
                if "month" in line or "week" in line:
                    price_label = line
                    break

            # Only follow the listing when we have a link to its detail page
            if url:
                # Put the card image into a list (empty list when there is none)
                images = []
                if image:
                    images.append(image)

                yield scrapy.Request(
                    url=url,
                    callback=self.parse_detail,
                    cb_kwargs={
                        "url": url,
                        "title": street,
                        "images": images,
                        "address": street,
                        "street": street,
                        "city": city,
                        "living_area": living_area,
                        "furnished": furnished,
                        "property_type": property_type,
                        "availability": availability,
                        "price": price,
                        "price_label": price_label,
                    },
                )

        # Go to the next results page if there is a next button that is not
        # disabled, and the current page actually had cards on it
        next_btn = response.css("button[aria-label='Go to next page']")

        if cards and next_btn and "disabled" not in next_btn.attrib:
            next_page = page + 1
            yield scrapy.Request(
                url=f"https://kamernet.nl/en/for-rent/properties-{self.city}?pageNo={next_page}",
                callback=self.parse,
                cb_kwargs={"page": next_page},
            )

    def parse_detail(self, response, **kwargs):
        description_parts = response.css("section.About_root__a4NUR pre p::text").getall()
        description_pieces = []
        for part in description_parts:
            piece = part.strip()
            if piece != "":
                description_pieces.append(piece)
        description = " ".join(description_pieces)

        # "What you'll get" amenities, for example "Private kitchen"
        amenities = response.css("section.Details_root__6__Gy .Details_gridItem__ids4p p.MuiTypography-body1::text").getall()

        energy_label = ""
        for amenity in amenities:
            text = amenity.strip()
            if text.startswith("Energy label"):
                energy_label = text[len("Energy label"):].strip()

        # Rental costs: deposit and any extra monthly costs
        cost_rows = response.css("section.RentalCosts_root__mUggN .RentalCosts_cardRow__RilZB")
        deposit_raw = ""
        additional_costs_raw = ""
        for row in cost_rows:
            label = row.css("p::text").get("").strip()
            value = row.css("h6::text").get("").strip()
            if "Deposit" in label:
                deposit_raw = value
            elif "Additional" in label:
                additional_costs_raw = value

        # These are money amounts, store them as plain numbers (None if missing)
        deposit = extract_number(deposit_raw)
        additional_costs = extract_number(additional_costs_raw)

        # Whether utilities are included is shown in the price label, for example "/month incl. utilities".
        # turn that into a short tag.
        # The label only mentions utilities when they are included, so if it is not mentioned treat utilities as not included.
        price_label = kwargs.get("price_label", "")
        if "incl. utilities" in price_label.lower():
            utilities = "Incl. utilities"
        else:
            utilities = "Excl. utilities"

        rental_period = ""
        overview_notes = response.css(
            "section.Overview_root__CNI03 .PropertyDetails_row___QmRn p.MuiTypography-body4::text"
        ).getall()
        for note in overview_notes:
            note = note.strip()
            if "period" in note.lower():
                rental_period = note

        tags = []
        for amenity in amenities:
            amenity = amenity.strip()
            if amenity != "" and amenity not in tags:
                tags.append(amenity)

        furnished = kwargs.get("furnished", "")
        property_type = kwargs.get("property_type", "")
        extra_tags = [utilities, furnished, property_type, rental_period]
        for extra in extra_tags:
            extra = extra.strip()
            if extra != "" and extra not in tags:
                tags.append(extra)

        # The landlords "ideal tenant": each row is a label and a value
        # keep the value only, and turn "Number of tenants: 2" into {"Number of tenants": 2}
        tenant_rows = response.css("section.IdealTenant_root__TS7M8 .IdealTenant_row__U4412")
        ideal_tenant = {}
        for row in tenant_rows:
            texts = row.css("p::text").getall()
            if len(texts) == 2:
                key = texts[0].strip()
                val = texts[1].strip()
                if key == "Number of tenants":
                    number = extract_number(val)
                    if number is not None:
                        val = number
                elif key == "Age":
                    # Drop the word "years", keep just the range.
                    val = re.sub(r"\s*years$", "", val)
                    val = val.strip()
                ideal_tenant[key] = val

        landlord_name = response.css("section.LandlordInfo_root__1KSuS h6.MuiTypography-subtitle1::text").get("").strip()
        landlord_type = response.css(".LandlordProfile_status___CzI5 p::text").get("").strip()

        posted = response.css("section.Header_root__n5yMv .Header_row__cNlOA p.MuiTypography-body3::text").get("").strip()

        listing = {}
        for key in kwargs:
            listing[key] = kwargs[key]

        # The card only gave us one low-quality thumbnail. The detail page has
        # the full set of high-quality photos, so use those when we can find
        # them. If we cannot, keep the card image we already have.
        detail_images = detail_page_images(response)
        if detail_images:
            listing["images"] = detail_images

        latitude, longitude = detail_page_coordinates(response)
        listing["latitude"] = latitude
        listing["longitude"] = longitude

        # Kamernet only shows rooms that are for rent, so the status is always
        # "Available". availability (in kwargs) holds the move-in date.
        listing["status"] = "Available"
        listing["description"] = description
        listing["amenities"] = amenities
        listing["tags"] = tags
        listing["energy_label"] = energy_label
        listing["utilities"] = utilities
        listing["deposit"] = deposit
        listing["additional_costs"] = additional_costs
        listing["rental_period"] = rental_period
        listing["ideal_tenant"] = ideal_tenant
        listing["landlord_name"] = landlord_name
        listing["landlord_type"] = landlord_type
        listing["posted"] = posted

        yield listing
