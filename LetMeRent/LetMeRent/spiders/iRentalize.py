import scrapy
import re

from LetMeRent.spiders.city_utils import city_title


class IRentalizeSpider(scrapy.Spider):
    name = "irentalize"
    allowed_domains = ["irentalize.nl"]
    start_urls = ["https://irentalize.nl/properties/"]

    def __init__(self, city=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.city = city_title(city)

    def start_requests(self):
        yield scrapy.Request(
            url=self.start_urls[0],
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

        seen = set()
        page_number = 1

        try:
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(4000)

            try:
                await page.get_by_role("button", name="Accept").click(timeout=3000)
            except Exception:
                pass

            city_select = page.locator("select.jet-select__control[name='city']")
            await city_select.wait_for(timeout=10000)
            await city_select.select_option(value=city)
            await city_select.dispatch_event("change")

            await page.wait_for_timeout(2000)

            await page.locator("button.apply-filters__button").click()
            await page.wait_for_timeout(5000)

            while True:
                self.logger.info(f"SCRAPING CITY {city} PAGE {page_number}")

                html = await page.content()
                selector = scrapy.Selector(text=html)

                property_links = selector.css(
                    "a[href*='/properties/']::attr(href), "
                    "a[href*='/property/']::attr(href)"
                ).getall()

                for href in property_links:
                    if not href:
                        continue

                    if href == "/properties/":
                        continue

                    full_url = response.urljoin(href)

                    if full_url in seen:
                        continue

                    seen.add(full_url)

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

                next_clicked = await self.click_next_page(page)

                if not next_clicked:
                    self.logger.info(f"NO MORE PAGES FOR {city}")
                    break

                page_number += 1
                await page.wait_for_timeout(5000)

        finally:
            await page.close()

    async def click_next_page(self, page):
        try:
            current = page.locator(
                ".jet-filters-pagination__item.jet-filters-pagination__current"
            )

            if await current.count() == 0:
                return False

            current_value = await current.first.get_attribute("data-value")

            if not current_value:
                return False

            next_page = str(int(current_value) + 1)

            next_button = page.locator(
                f".jet-filters-pagination__item[data-value='{next_page}']"
            )

            if await next_button.count() == 0:
                return False

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

        headings = [
            text.strip()
            for text in response.css(".elementor-heading-title::text").getall()
            if text.strip()
        ]

        all_text = " ".join(
            text.strip()
            for text in response.css("body ::text").getall()
            if text.strip()
        )

        images = response.css(
            "img::attr(src), "
            ".e-gallery-image::attr(data-thumbnail)"
        ).getall()

        images = list(dict.fromkeys(images))

        landlord = response.css(".elementor-author-box__name::text").get()
        status = self.extract_status(headings, all_text)
        starting_price = self.extract_starting_price(all_text)
        base_rent = self.extract_base_rent(all_text)

        yield {
            "city_filter": response.meta.get("city_filter"),
            "listing_page": response.meta.get("listing_page"),
            "url": response.url,
            "title": title.strip() if title else None,
            "property_type": self.extract_property_type(headings),
            "city": self.extract_city(headings, all_text),
            "living_area": self.extract_size(all_text),
            "rooms": self.extract_rooms(all_text),
            "availability": status,
            "status": status,
            "price": starting_price or base_rent,
            "starting_price": starting_price,
            "base_rent": base_rent,
            "service_fee": self.extract_service_fee(all_text),
            "utilities": self.extract_utilities(all_text),
            "images": images,
            "description": all_text,
            "landlord_name": landlord.strip() if landlord else None,
        }

    def extract_property_type(self, headings):
        for heading in headings:
            if heading in ["Rooms", "Room", "House", "Studio", "Appartment", "Apartment"]:
                return heading
        return None

    def extract_city(self, headings, text):
        for heading in headings:
            if "for rent in" in heading:
                return heading.replace("for rent in", "").strip()

        if "for rent in" in text:
            return text.split("for rent in", 1)[1].split()[0].strip()

        return None

    def extract_status(self, headings, text):
        for word in ["RENTED", "AVAILABLE", "RESERVED"]:
            if word in headings or word in text:
                return word
        return None

    def extract_size(self, text):
        if "m²" in text:
            before = text.split("m²", 1)[0]
            return before.split()[-1] + "m²"
        return None

    def extract_rooms(self, text):
        if " rooms" in text:
            before = text.split(" rooms", 1)[0]
            return before.split()[-1] + " rooms"

        if " room" in text:
            before = text.split(" room", 1)[0]
            return before.split()[-1] + " room"

        return None

    def clean_price(self, value):
        if not value:
            return None

        number = re.sub(r"[^\d]", "", value)

        return number if number else None

    def extract_starting_price(self, text):
        if "Starting from:" in text:
            price = text.split("Starting from:", 1)[1].split("Includes:", 1)[0].strip()
            return self.clean_price(price)
        return None

    def extract_base_rent(self, text):
        if "Base rent:" in text:
            price = text.split("Base rent:", 1)[1].split()[0].strip()
            return self.clean_price(price)
        return None

    def extract_service_fee(self, text):
        if "Includes:" in text and "service fee" in text:
            part = text.split("Includes:", 1)[1].split("service fee", 1)[0]
            return self.clean_price(part)
        return None

    def extract_utilities(self, text):
        if "utilities" in text:
            part = text.split("utilities", 1)[0]
            value = part.split()[-1].strip()
            return self.clean_price(value)
        return None
