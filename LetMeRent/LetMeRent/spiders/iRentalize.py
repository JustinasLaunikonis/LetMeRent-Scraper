import scrapy
import re


class IRentalizeSpider(scrapy.Spider):

    # Spider name used in terminal command:
    # scrapy crawl irentalize
    name = "irentalize"

    # Allowed domain for crawling
    allowed_domains = ["irentalize.nl"]

    # Main page with all properties
    start_urls = [
        "https://irentalize.nl/properties/"
    ]

    # Cities that will be selected in filters
    cities = [
        "Emmen",
        "Leeuwarden"
    ]

    # Start requests for every city
    def start_requests(self):

        for city in self.cities:

            yield scrapy.Request(
                url=self.start_urls[0],

                # Playwright configuration
                meta={
                    "playwright": True,
                    "playwright_include_page": True,
                    "city": city,
                },

                callback=self.parse_city,

                # Prevent Scrapy duplicate filtering
                dont_filter=True,
            )

    # Parse listing pages
    async def parse_city(self, response):

        # Get Playwright page
        page = response.meta["playwright_page"]

        # Current selected city
        city = response.meta["city"]

        # Prevent duplicate URLs
        seen = set()

        # Track pagination page number
        page_number = 1

        try:

            # Wait until page fully loads
            await page.wait_for_load_state("networkidle")

            await page.wait_for_timeout(4000)

            # Accept cookies popup if exists
            try:

                await page.get_by_role(
                    "button",
                    name="Accept"
                ).click(timeout=3000)

            except Exception:
                pass

            # Find city dropdown
            city_select = page.locator(
                "select.jet-select__control[name='city']"
            )

            await city_select.wait_for(timeout=10000)

            # Select city
            await city_select.select_option(value=city)

            # Trigger frontend JS update
            await city_select.dispatch_event("change")

            await page.wait_for_timeout(2000)

            # Click Find property button
            await page.locator(
                "button.apply-filters__button"
            ).click()

            # Wait results refresh
            await page.wait_for_timeout(5000)

            # Pagination loop
            while True:

                self.logger.info(
                    f"SCRAPING CITY {city} PAGE {page_number}"
                )

                # Get page HTML
                html = await page.content()

                selector = scrapy.Selector(text=html)

                # Collect property links
                property_links = selector.css(
                    "a[href*='/properties/']::attr(href), "
                    "a[href*='/property/']::attr(href)"
                ).getall()

                # Loop through every property
                for href in property_links:

                    # Skip empty links
                    if not href:
                        continue

                    # Skip main listing page
                    if href == "/properties/":
                        continue

                    # Create full absolute URL
                    full_url = response.urljoin(href)

                    # Skip duplicates
                    if full_url in seen:
                        continue

                    seen.add(full_url)

                    # Open property page
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

                # Go to next pagination page
                next_clicked = await self.click_next_page(page)

                # Stop if no next page
                if not next_clicked:

                    self.logger.info(
                        f"NO MORE PAGES FOR {city}"
                    )

                    break

                page_number += 1

                await page.wait_for_timeout(5000)

        finally:

            # Close Playwright page
            await page.close()

    # Handle pagination
    async def click_next_page(self, page):

        try:

            # Find current active page
            current = page.locator(
                ".jet-filters-pagination__item.jet-filters-pagination__current"
            )

            if await current.count() == 0:
                return False

            # Current page number
            current_value = await current.first.get_attribute(
                "data-value"
            )

            if not current_value:
                return False

            # Calculate next page number
            next_page = str(int(current_value) + 1)

            # Find next page button
            next_button = page.locator(
                f".jet-filters-pagination__item[data-value='{next_page}']"
            )

            # Stop if next page does not exist
            if await next_button.count() == 0:
                return False

            # Scroll to pagination
            await next_button.first.scroll_into_view_if_needed()

            await page.wait_for_timeout(1000)

            # Click next page
            await next_button.first.click(force=True)

            # Wait new content load
            await page.wait_for_timeout(5000)

            return True

        except Exception as e:

            self.logger.info(
                f"PAGINATION ERROR: {e}"
            )

            return False

    # Parse individual property page
    def parse_property(self, response):

        # Property title
        title = response.css(
            "h1.elementor-heading-title::text"
        ).get()

        # Collect all heading texts
        headings = [
            text.strip()
            for text in response.css(
                ".elementor-heading-title::text"
            ).getall()
            if text.strip()
        ]

        # Get all visible text from page
        all_text = " ".join(
            text.strip()
            for text in response.css(
                "body ::text"
            ).getall()
            if text.strip()
        )

        # Collect all images
        images = response.css(
            "img::attr(src), "
            ".e-gallery-image::attr(data-thumbnail)"
        ).getall()

        # Remove duplicates
        images = list(dict.fromkeys(images))

        # Remove first image because usually it is iRentalize logo
        if images:
            images = images[1:]

        # Landlord name
        landlord = response.css(
            ".elementor-author-box__name::text"
        ).get()

        # Extract status
        status = self.extract_status(
            headings,
            all_text
        )

        # Final structured data
        yield {

            "city_filter": response.meta.get("city_filter"),

            "listing_page": response.meta.get("listing_page"),

            "url": response.url,

            "title": title.strip() if title else None,

            "property_type": self.extract_property_type(headings),

            "city": self.extract_city(
                headings,
                all_text
            ),

            "size": self.extract_size(all_text),

            "rooms": self.extract_rooms(all_text),

            "status": status,

            "starting_price": self.extract_starting_price(all_text),

            "base_rent": self.extract_base_rent(all_text),

            "service_fee": self.extract_service_fee(all_text),

            "utilities": self.extract_utilities(all_text),

            "landlord": landlord.strip() if landlord else None,

            "chat_url": response.css(
                "a.bpbm-pm-button::attr(href)"
            ).get(),

            "images": images,

            "description": all_text,
        }

    # Extract property type
    def extract_property_type(self, headings):

        for heading in headings:

            if heading in [
                "Rooms",
                "Room",
                "House",
                "Studio",
                "Appartment",
                "Apartment"
            ]:
                return heading

        return None

    # Extract city
    def extract_city(self, headings, text):

        for heading in headings:

            if "for rent in" in heading:

                return heading.replace(
                    "for rent in",
                    ""
                ).strip()

        if "for rent in" in text:

            return text.split(
                "for rent in",
                1
            )[1].split()[0].strip()

        return None

    # Extract property status
    def extract_status(self, headings, text):

        for word in [
            "RENTED",
            "AVAILABLE",
            "RESERVED"
        ]:

            if word in headings or word in text:
                return word

        return None

    # Extract size only as number
    # Example:
    # "6.2m²" -> "6.2"
    def extract_size(self, text):

        match = re.search(
            r"(\d+(?:\.\d+)?)\s*m²",
            text
        )

        if match:
            return match.group(1)

        return None

    # Extract rooms count only as number
    # Example:
    # "1 room" -> "1"
    def extract_rooms(self, text):

        # Primary pattern
        match = re.search(
            r"\d+(?:\.\d+)?\s*m²\s*-\s*\d+(?:\.\d+)?\s*m²,\s*(\d+)\s+rooms?",
            text,
            re.IGNORECASE
        )

        if match:
            return match.group(1)

        # Backup pattern
        match = re.search(
            r"for rent in\s+[A-Za-z]+\s+\d+(?:\.\d+)?\s*m²\s*-\s*\d+(?:\.\d+)?\s*m²,\s*(\d+)\s+rooms?",
            text,
            re.IGNORECASE
        )

        if match:
            return match.group(1)

        return None

    # Clean prices
    # Example:
    # "€450" -> "450"
    def clean_price(self, value):

        if not value:
            return None

        number = re.sub(
            r"[^\d]",
            "",
            value
        )

        return number if number else None

    # Extract starting price
    def extract_starting_price(self, text):

        if "Starting from:" in text:

            price = text.split(
                "Starting from:",
                1
            )[1].split(
                "Includes:",
                1
            )[0].strip()

            return self.clean_price(price)

        return None

    # Extract base rent
    def extract_base_rent(self, text):

        if "Base rent:" in text:

            price = text.split(
                "Base rent:",
                1
            )[1].split()[0].strip()

            return self.clean_price(price)

        return None

    # Extract service fee
    def extract_service_fee(self, text):

        if "Includes:" in text and "service fee" in text:

            part = text.split(
                "Includes:",
                1
            )[1].split(
                "service fee",
                1
            )[0]

            return self.clean_price(part)

        return None

    # Extract utilities price
    def extract_utilities(self, text):

        if "utilities" in text:

            part = text.split(
                "utilities",
                1
            )[0]

            value = part.split()[-1].strip()

            return self.clean_price(value)

        return None