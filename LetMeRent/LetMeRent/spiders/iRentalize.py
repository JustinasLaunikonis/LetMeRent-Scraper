import scrapy
import re
from urllib.parse import quote

from LetMeRent.spiders.city_utils import city_title, normalize_status, normalize_availability, address_coordinates


def extract_number(text):
    # Keep only the digits from the text, so "3 Bathroom(s)" becomes 3
    # Returns None when there is no number at all
    if text is None:
        return None

    digits_only = re.sub(r"[^\d]", "", text)

    if digits_only == "":
        return None

    return int(digits_only)


class IRentalizeSpider(scrapy.Spider):
    name = "irentalize"
    allowed_domains = ["irentalize.nl"]
    base_url = "https://irentalize.nl/properties/"

    def __init__(self, city=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.city = city_title(city)

    def build_start_url(self):
        city = quote(self.city, safe="")
        return f"{self.base_url}?jsf=jet-engine:filterproperty&meta=city:{city}"

    def start_requests(self):
        # The site loads its listings with JavaScript, use Playwright to open a real browser page
        # keep the page open (with "playwright_include_page") so we can click the pagination buttons in parse_city.
        yield scrapy.Request(
            url=self.build_start_url(),
            meta={
                "playwright": True,
                "playwright_include_page": True,
                "city": self.city,
            },
            callback=self.parse_city,
            dont_filter=True,
        )

    async def parse_city(self, response):
        page = response.meta["playwright_page"]
        city = response.meta["city"]

        # Keep track of the listing links we have already seen, so we do not
        # scrape the same property twice across pages.
        seen = set()
        page_number = 1

        try:
            # Wait until the page has finished loading before we touch it
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(4000)

            # Close the cookie banner if it shows up.
            # It is fine if there is no banner, so we ignore any error here.
            try:
                await page.get_by_role("button", name="Accept").click(timeout=3000)
            except Exception:
                pass

            # Go through the result pages one by one until there are no more
            while True:
                self.logger.info(f"SCRAPING CITY {city} PAGE {page_number}")

                # Read the current page HTML and turn it into a selector we can search through
                html = await page.content()
                selector = scrapy.Selector(text=html)

                property_links = selector.css(
                    "a[href*='/properties/']::attr(href), "
                    "a[href*='/property/']::attr(href)"
                ).getall()

                for href in property_links:
                    if not href:
                        continue

                    # Skip the link that just points back to the list itself
                    if href == "/properties/":
                        continue

                    full_url = response.urljoin(href)

                    # Skip links we have already queued
                    if full_url in seen:
                        continue

                    seen.add(full_url)

                    # Open each property detail page to scrape its fields
                    yield scrapy.Request(
                        url=full_url,
                        callback=self.parse_property,
                        meta={
                            "city_filter": city,
                            "listing_page": page_number,
                            "playwright": True,
                        },
                        dont_filter=True,
                    )

                # Try to move to the next page. If we cannot, finish
                next_clicked = await self.click_next_page(page)

                if not next_clicked:
                    self.logger.info(f"NO MORE PAGES FOR {city}")
                    break

                page_number = page_number + 1
                await page.wait_for_timeout(5000)

        finally:
            # Always close the browser page, even if something went wrong
            await page.close()

    async def click_next_page(self, page):
        try:
            # Find the pagination item that is marked as the current page
            current = page.locator(
                ".jet-filters-pagination__item.jet-filters-pagination__current"
            )

            # No pagination on the page means there is nothing to click
            if await current.count() == 0:
                return False

            # The current page number is stored in a "data-value"
            current_value = await current.first.get_attribute("data-value")

            if not current_value:
                return False

            next_number = int(current_value) + 1
            next_page = str(next_number)

            next_button = page.locator(
                f".jet-filters-pagination__item[data-value='{next_page}']"
            )

            # If there is no button for the next number, weve reached the end
            if await next_button.count() == 0:
                return False

            # Scroll the button into view and click it, wait for load
            await next_button.first.scroll_into_view_if_needed()
            await page.wait_for_timeout(1000)
            await next_button.first.click(force=True)
            await page.wait_for_timeout(5000)

            return True

        except Exception as e:
            self.logger.info(f"PAGINATION ERROR: {e}")
            return False

    def parse_property(self, response):
        title = response.css("h1.elementor-heading-title::text").get()

        # Collect all the heading texts on the page
        headings = []
        raw_headings = response.css(".elementor-heading-title::text").getall()
        for heading_text in raw_headings:
            heading_text = heading_text.strip()
            if heading_text != "":
                headings.append(heading_text)

        # Collect the visible text on the page. 
        # skip the text inside <script> and <style> tags, otherwise the page's JavaScript and CSS
        # (like WordPress/Elementor config) would end up in the description
        text_nodes = response.xpath(
            "//body//text()[not(ancestor::script) and not(ancestor::style)]"
        ).getall()

        text_pieces = []
        for node in text_nodes:
            piece = node.strip()
            if piece != "":
                text_pieces.append(piece)
        all_text = " ".join(text_pieces)

        raw_images = response.css(
            "img::attr(src), "
            ".e-gallery-image::attr(data-thumbnail)"
        ).getall()

        # Remove duplicate images but keep their original order
        images = []
        for image in raw_images:
            if image not in images:
                images.append(image)

        # Remove the first image because it is usually the iRentalize logo
        if images:
            images = images[1:]

        landlord = response.css(".elementor-author-box__name::text").get()

        # iRentalize shows the state as a word like "RENTED" or "AVAILABLE".
        # That is the status, not a move-in date, so we store it as status
        raw_status = self.extract_status(headings, all_text)
        status = normalize_status(raw_status)
        starting_price = self.extract_starting_price(all_text)
        base_rent = self.extract_base_rent(all_text)

        description = self.extract_description(response)

        # "Furnished", "Balcony", "3 Bathroom(s)", "Energy Level: Unknown".
        features = self.extract_features(response)
        feature_info = self.read_feature_values(features)

        rooms = feature_info["rooms"]
        if rooms is None:
            rooms = self.extract_rooms(all_text)

        price = starting_price
        if price is None:
            price = base_rent

        if title:
            title = title.strip()
        else:
            title = None

        if landlord:
            landlord = landlord.strip()
        else:
            landlord = None

        # The title heading holds the street address (street + house number).
        # iRentalize does not give coordinates, so build a full address from
        # the title and the city and ask PDOK to turn it into latitude/longitude.
        city = self.extract_city(headings, all_text)
        full_address = ""
        if title:
            full_address = title
            if city:
                full_address = full_address + ", " + city

        latitude, longitude = address_coordinates(full_address)

        yield {
            "city_filter": response.meta.get("city_filter"),
            "listing_page": response.meta.get("listing_page"),
            "url": response.url,
            "title": title,
            "property_type": self.extract_property_type(headings),
            "city": city,
            "latitude": latitude,
            "longitude": longitude,

            # Number only, without m²
            "living_area": self.extract_size(all_text),

            # Number only, without "room" or "rooms"
            "rooms": rooms,
            "bathrooms": feature_info["bathrooms"],
            "kitchens": feature_info["kitchens"],
            "toilets": feature_info["toilets"],
            "floors": feature_info["floors"],

            "availability": normalize_availability(self.extract_availability(response)),
            "status": status,
            "price": price,
            "starting_price": starting_price,
            "base_rent": base_rent,
            "service_fee": self.extract_service_fee(all_text),
            "utilities": self.extract_utilities(all_text),
            "furnished": feature_info["furnished"],
            "energy_label": feature_info["energy_label"],
            "tags": feature_info["tags"],
            "images": images,
            "description": description,
            "landlord_name": landlord,
        }

    def extract_availability(self, response):
        # iRentalize shows the move-in info in a "dynamic field" whose text
        # starts with the word "Available", for example "Available from
        # June 1, 2026" or "Available immediately". We look through those fields
        # and keep just the move-in text (a status word never goes here).
        #
        # The description can also contain the word "available", but those
        # sentences start with other words (like "Only student room
        # available..."), so we only accept text that begins with "Available".
        field_texts = response.css(".jet-listing-dynamic-field__content::text").getall()
        for raw_text in field_texts:
            text = raw_text.strip()

            # "Available from June 1, 2026" -> keep just the date "June 1, 2026"
            if text.startswith("Available from"):
                date_text = text.replace("Available from", "", 1).strip()
                return date_text

            # "Available immediately" -> store the short phrase "Immediately"
            if text.startswith("Available immediately"):
                return "Immediately"

        return ""

    def extract_description(self, response):
        description_path = (
            "//*[contains(concat(' ', normalize-space(@class), ' '), "
            "' elementor-heading-title ')][normalize-space()='Description']"
            "/following::div[contains(concat(' ', normalize-space(@class), ' '), "
            "' elementor-widget-text-editor ')][1]//text()"
        )

        parts = []
        for piece in response.xpath(description_path).getall():
            piece = piece.strip()
            if piece != "":
                parts.append(piece)

        return " ".join(parts)

    def extract_features(self, response):
        feature_path = (
            "//span[contains(concat(' ', normalize-space(@class), ' '), "
            "' elementor-icon-list-text ')"
            " and not(ancestor::header)"
            " and not(ancestor::footer)"
            " and not(ancestor::*[contains(@class, 'jet-listing-grid')])]//text()"
        )

        features = []
        for raw_text in response.xpath(feature_path).getall():
            # some labels have double spaces.
            text = re.sub(r"\s+", " ", raw_text).strip()
            if text == "":
                continue
            # "More photos" is a gallery button, not a real "tag"
            if text == "More photos":
                continue
            features.append(text)

        return features

    def read_feature_values(self, features):
        # Sort the feature labels into useful fields and a list of tags
        info = {
            "rooms": None,
            "bathrooms": None,
            "kitchens": None,
            "toilets": None,
            "floors": None,
            "furnished": "",
            "energy_label": "",
            "tags": [],
        }

        for feature in features:
            if feature.startswith("Energy Level:"):
                grade = feature.split(":", 1)[1].strip()
                if grade.lower() != "unknown":
                    info["energy_label"] = grade
                continue

            # Count items like "3 Rooms" or "2 Floor(s)" start with a number
            number = extract_number(feature)
            if number is not None:
                if "Bathroom" in feature:
                    info["bathrooms"] = number
                elif "Rooms" in feature:
                    info["rooms"] = number
                elif "Floor" in feature:
                    info["floors"] = number
                elif "Kitchen" in feature:
                    info["kitchens"] = number
                elif "Toilet" in feature:
                    info["toilets"] = number
                continue

            # Anything left is a descriptive feature, so save it as a tag.
            if feature == "Furnished":
                info["furnished"] = "Furnished"
            info["tags"].append(feature)

        return info

    def extract_property_type(self, headings):
        # The property type is one of these words when it shows up as a heading
        known_types = ["Rooms", "Room", "House", "Studio", "Appartment", "Apartment"]
        for heading in headings:
            if heading in known_types:
                return heading
        return None

    def extract_city(self, headings, text):
        # First try the headings, which look like "Studio for rent in Emmen"
        for heading in headings:
            if "for rent in" in heading:
                city_name = heading.replace("for rent in", "")
                return city_name.strip()

        # Otherwise look for the same phrase in the page text and take the first word right after it
        if "for rent in" in text:
            after_phrase = text.split("for rent in", 1)[1]
            words = after_phrase.split()
            if len(words) > 0:
                return words[0].strip()

        return None

    def extract_status(self, headings, text):
        # The site shows the state as one of these words.
        # Return the first one we find in either the headings or the page text
        for word in ["RENTED", "AVAILABLE", "RESERVED"]:
            if word in headings or word in text:
                return word
        return None

    def extract_size(self, text):
        match = re.search(
            r"(\d+(?:\.\d+)?)\s*m²",
            text
        )

        if match:
            # Store the surface area as a plain number (no "m²")
            # A few listings use a decimal like "12.5", so keep those as floats.
            value = match.group(1)
            if "." in value:
                return float(value)
            return int(value)

        return None

    def extract_rooms(self, text):
        match = re.search(
            r"\d+(?:\.\d+)?\s*m²\s*-\s*\d+(?:\.\d+)?\s*m²,\s*(\d+)\s+rooms?",
            text,
            re.IGNORECASE
        )

        if match:
            # Store the number of rooms as a plain number.
            return int(match.group(1))

        match = re.search(
            r"for rent in\s+[A-Za-z]+\s+\d+(?:\.\d+)?\s*m²\s*-\s*\d+(?:\.\d+)?\s*m²,\s*(\d+)\s+rooms?",
            text,
            re.IGNORECASE
        )

        if match:
            # Store the number of rooms as a plain number.
            return int(match.group(1))

        return None

    def clean_price(self, value):
        if not value:
            return None

        # Keep only the digits and store the price as a plain number.
        number = re.sub(r"[^\d]", "", value)

        if number == "":
            return None

        return int(number)

    def extract_starting_price(self, text):
        # The starting price sits between "Starting from:" and "Includes:".
        if "Starting from:" not in text:
            return None

        after_label = text.split("Starting from:", 1)[1]
        price_part = after_label.split("Includes:", 1)[0]
        price_part = price_part.strip()
        return self.clean_price(price_part)

    def extract_base_rent(self, text):
        # The base rent is the first word right after "Base rent:"
        if "Base rent:" not in text:
            return None

        after_label = text.split("Base rent:", 1)[1]
        words = after_label.split()
        if len(words) == 0:
            return None

        first_word = words[0].strip()
        return self.clean_price(first_word)

    def extract_service_fee(self, text):
        # The service fee is the amount shown between "Includes:" and "service fee".
        if "Includes:" in text and "service fee" in text:
            after_includes = text.split("Includes:", 1)[1]
            before_fee = after_includes.split("service fee", 1)[0]
            return self.clean_price(before_fee)
        return None

    def extract_utilities(self, text):
        # The utilities amount is the last word right before "utilities"
        if "utilities" in text:
            before_utilities = text.split("utilities", 1)[0]
            words = before_utilities.split()
            if len(words) == 0:
                return None

            last_word = words[-1].strip()
            return self.clean_price(last_word)
        return None
