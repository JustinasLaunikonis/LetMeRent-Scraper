import re
import json
import scrapy

from LetMeRent.spiders.city_utils import city_slug, normalize_status, normalize_availability

LISTING_SELECTOR = '[data-testid="listingDetailsAddress"]'

def digits_only(value):
    # Keep only the digits from a value, so "105 m²" becomes 105
    # Returns None when there is no number at all
    text = str(value or "")
    number_text = re.sub(r"[^\d]", "", text)
    if number_text == "":
        return None
    return int(number_text)


def leading_number(value):
    # "€ 2,415" becomes 2415 and "2009" becomes 2009.
    # returns the original value when there is no number at all
    without_euro = re.sub(r"^€\s*", "", value.strip())
    match = re.match(r"[\d,\.]+", without_euro)
    if not match:
        return value

    number_text = re.sub(r"[^\d]", "", match.group())
    if number_text == "":
        return value
    return int(number_text)


def text_of(node):
    # Read all the text inside a page element and join it into one clean string with single spaces
    parts = node.css("::text").getall()
    joined = " ".join(parts)
    return joined.strip()


class FundaSpider(scrapy.Spider):
    name = "funda"
    allowed_domains = ["funda.nl"]

    def __init__(self, city=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.city = city_slug(city)

    def start_requests(self):
        # Start at page 1 of the rental search for the chosen city
        first_page = self._search_url(1)
        yield scrapy.Request(first_page, callback=self.parse, cb_kwargs={"page": 1})

    def _search_url(self, page):
        # Build the search URL for one page of results
        return f'https://www.funda.nl/en/zoeken/huur?selected_area=["{self.city}"]&page={page}'

    def parse(self, response, page=1):
        # Read one page of search results and follow each listing link
        listings = response.css(LISTING_SELECTOR)
        self.logger.info(f"Page {page}: found {len(listings)} listings")

        for address_link in listings:
            href = address_link.attrib.get("href", "")
            if href:
                # Skip "koophuur" listings (buy-and-rent). We only want normal
                # rentals, so we do not follow any link that has /koophuur/ in it.
                if "/koophuur/" in href:
                    continue
                # Open the listing page to read its details.
                yield response.follow(href, callback=self.parse_detail)

        # If this page had listings, there could be another page after it
        if listings:
            next_page = self._search_url(page + 1)
            yield scrapy.Request(next_page, callback=self.parse, cb_kwargs={"page": page + 1})

    def _deref(self, arr, idx):
        # Funda stores all data in one big list
        # Many values are not kept directly but instead they are a number that points to another spot in the same list.
        # This function follows that number to get the real value.
        # It calls itself again when a value points somewhere else.

        # The number must be a valid position in the list
        if not isinstance(idx, int):
            return None
        if idx < 0 or idx >= len(arr):
            return None

        value = arr[idx]

        if isinstance(value, list):
            # Funda wraps some values like ["Reactive", 1234].
            # In that case the real value is at the position given by the second item.
            is_wrapper = (
                len(value) > 0
                and isinstance(value[0], str)
                and value[0] in ("ShallowReactive", "Reactive", "Set")
            )
            if is_wrapper:
                if len(value) > 1:
                    return self._deref(arr, value[1])
                else:
                    return None

            # A normal list: go through each item.
            # If an item is a number it points somewhere else, follow it.
            # Otherwise keep it as is.
            result_list = []
            for item in value:
                if isinstance(item, int):
                    result_list.append(self._deref(arr, item))
                else:
                    result_list.append(item)
            return result_list

        # A dict works the same way: each value may point somewhere else.
        if isinstance(value, dict):
            result_dict = {}
            for key in value:
                inner = value[key]
                if isinstance(inner, int):
                    result_dict[key] = self._deref(arr, inner)
                else:
                    result_dict[key] = inner
            return result_dict

        # A plain value (text, number, etc.) is returned directly.
        return value

    def _nuxt_listing(self, response):
        # Funda keeps all the listing data inside a
        # <script id="__NUXT_DATA__"> tag as one big JSON list.
        # Read that list and find the listing data inside it.
        raw = response.css("script#__NUXT_DATA__::text").get("")
        if not raw:
            return {}

        try:
            arr = json.loads(raw)
        except Exception:
            # If the JSON cannot be read, return an empty result.
            return {}

        # Look for the entry that holds the listing data.
        # Funda keeps it under "cachedListingData".
        for item in arr:
            if isinstance(item, dict):
                for key in item:
                    if key.startswith("cachedListingData"):
                        listing = self._deref(arr, item[key])
                        if listing:
                            return listing
                        else:
                            return {}

        return {}

    def parse_detail(self, response):
        if "/koophuur/" in response.url:
            return

        listing = self._nuxt_listing(response)

        price_obj = listing.get("price") or {}
        fv = listing.get("featuresFastView") or {}
        desc_obj = listing.get("description") or {}
        addr = listing.get("address") or {}
        coords = listing.get("coordinates") or {}

        # Price is already a number in the Funda data.
        price = price_obj.get("numericPrice")

        # These come as text like "105 m²", so we keep only the number.
        living_area = digits_only(fv.get("livingArea"))
        plot_size = digits_only(fv.get("plotArea"))
        bedrooms = digits_only(fv.get("numberOfBedrooms"))

        # Keep the energy label as a clean grade (c, b, a, etc.), or "" when there is none
        # so it is stored the same way as the other spiders.
        energy_label = fv.get("energyLabel") or ""

        description = (desc_obj.get("content") or "").strip()

        lat = coords.get("lat")
        lng = coords.get("lng")

        # Street name: use the data value, or read it from the page heading.
        street = addr.get("addressTitle")
        if not street:
            street = response.css("h1[data-global-id] span.block::text").get("").strip()

        # Postal code + city line, for example "7811 AB Emmen".
        postal_city = addr.get("addressSubtitle")
        if not postal_city:
            postal_city = response.css("h1[data-global-id] .text-neutral-40::text").get("").strip()

        # Remove the postal code from the front so only the city name is left.
        city = re.sub(r"^\d{4}\s?[A-Z]{2}\s*", "", postal_city).strip()
        if city == "":
            city = None

        # Neighbourhood name: use the data value, or read it from the heading.
        neighbourhood = ""
        neighborhood_obj = addr.get("neighborhood")
        if neighborhood_obj:
            neighbourhood = neighborhood_obj.get("name")
        if not neighbourhood:
            neighbourhood = response.css("h1[data-global-id] a::text").get("").strip()

        # A few feature rows make good short "tags" (chips) for the listing on frontend.
        tag_keys = [
            "Type apartment",
            "Kind of house",
            "Status",
            "Building type",
            "Interior",
            "Bathroom facilities",
            "Number of bath rooms",
            "Insulation",
            "Rental agreement",
            "Acceptance",
        ]

        # The detail page shows feature tables.
        # Each row has a label (dt) and a value (dd).
        # Read them all into a dictionary, and also collect the chosen rows as tags.
        features = {}
        tags = []
        # We always remember the status text so we can set the standard status
        # field below. But "Available" is the normal case, so we do not keep it
        # in features or as a tag (that would just clutter the card). Every other
        # status ("Rented", "Under option", "Reserved", ...) is kept as usual.
        raw_status = ""
        for category in response.css('[data-testid^="category-"]'):
            dt_list = category.css("dt")
            dd_list = category.css("dd")

            pair_count = min(len(dt_list), len(dd_list))
            for i in range(pair_count):
                key = text_of(dt_list[i])
                val = text_of(dd_list[i])

                if key == "" or val == "":
                    continue

                # Remember the status text for the status field below.
                # Skip storing it only when it is "Available"; keep all other states.
                if key == "Status":
                    raw_status = val
                    if val.strip().lower() == "available":
                        continue

                # Values that start with "€" or a digit are amounts/sizes, so store the number only.
                # Everything else stays as text.
                if val.startswith("€") or re.match(r"^\d", val):
                    features[key] = leading_number(val)
                else:
                    features[key] = val

                # Collect the chosen rows as tags
                if key in tag_keys and val not in tags:
                    tags.append(val)

        # Show the energy label as a tag too
        if energy_label:
            tags.append("Energy label " + energy_label)

        # Common status / availability fields, stored the same way as the other spiders.
        # "Acceptance" is the move-in text (for example "Available immediately" or "Available on 8/1/2026")
        # "Status" is the listing state (for example "Available" or "Under option")
        availability = normalize_availability(features.get("Acceptance", ""))
        status = normalize_status(raw_status)

        # Agent details and the main photo
        agent_person = response.css("span.wrap-break-word::text").get("").strip()
        agent = response.css('h3 a[href*="/makelaar/"]::text').get("").strip()
        agent_url = response.css('h3 a[href*="/makelaar/"]::attr(href)').get("")

        phone_href = response.css('a[href^="tel:"]::attr(href)').get("")
        phone = ""
        if phone_href:
            phone = phone_href.replace("tel:", "")

        # Build the list of photo URLs from the listing data we already read.
        # This works even when the page layout changes, sometimes Funda shows a gallery, sometimes just one photo
        images = []
        media = listing.get("media") or {}
        photos = media.get("photos") or {}
        base_url = photos.get("mediaBaseUrl") or ""
        photo_items = photos.get("items") or []
        if base_url:
            for photo in photo_items:
                photo_id = photo.get("id")
                if photo_id:
                    image_url = base_url.replace("{id}", photo_id)
                    images.append(image_url)

        # Fallbacks in case the data had no photos
        if not images:
            og_image = response.css('meta[property="og:image"]::attr(content)').get("")
            if og_image:
                images = [og_image]
        if not images:
            image = response.css("#media .col-span-2 img::attr(src)").get("")
            if image:
                images = [image]

        yield {
            "url": response.url,
            "title": street,
            "address": street,
            "city": city,
            "street": street,
            "postal_city": postal_city,
            "neighbourhood": neighbourhood,
            "latitude": lat,
            "longitude": lng,
            "price": price,
            "living_area": living_area,
            "plot_size": plot_size,
            "rooms": bedrooms,
            "bedrooms": bedrooms,
            "energy_label": energy_label,
            "status": status,
            "availability": availability,
            "description": description,
            "agent_person": agent_person,
            "agent": agent,
            "agent_url": agent_url,
            "phone": phone,
            "images": images,
            "features": features,
            "tags": tags,
        }
