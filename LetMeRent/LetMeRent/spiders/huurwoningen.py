import re
import scrapy


class HuurwoningenSpider(scrapy.Spider):
    name = "huurwoningen"
    allowed_domains = ["huurwoningen.nl"]

    def __init__(self, city=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        raw_city = city or "emmen"
        self.city_name = raw_city.lower()
        self.city = self.city_name.replace(" ", "-")

    async def start(self):
        url = f"https://www.huurwoningen.nl/en/in/{self.city}"
        yield scrapy.Request(url=url, callback=self.parse)

    def parse(self, response):
        cards = response.css("section.listing-search-item")

        for card in cards:
            title = card.css(".listing-search-item__link--title::text").get("").strip()
            raw_address = card.css(".listing-search-item__sub-title::text").get("").strip()
            address = raw_address.split("(")[0].strip()
            raw_price = card.css(".listing-search-item__price-main::text").get("")
            price_match = re.search(r"[\d.]+", raw_price.replace(".", "").replace(",", ""))
            price = price_match.group() if price_match else ""
            raw_size = card.css(".illustrated-features__item--surface-area::text").get("")
            size_match = re.search(r"\d+", raw_size)
            size = size_match.group() if size_match else ""

            raw_rooms = card.css(".illustrated-features__item--number-of-rooms::text").get("")
            rooms_match = re.search(r"\d+", raw_rooms)
            rooms = rooms_match.group() if rooms_match else ""
            href = card.css(".listing-search-item__link--title::attr(href)").get()
            image = card.css(".picture__image::attr(src)").get()

            if href:
                yield response.follow(
                    href,
                    callback=self.parse_detail,
                    cb_kwargs={
                        "title": title,
                        "address": address,
                        "price": price,
                        "living_area": size,
                        "rooms": rooms,
                        "images": [image] if image else [],
                        "url": response.urljoin(href),
                    },
                )

        next_page = response.css(".pagination__item--next a::attr(href)").get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)

    def parse_detail(self, response, **kwargs):
        description_parts = response.css(".listing-detail-description__truncated::text").getall()
        description = " ".join(t.strip() for t in description_parts if t.strip())

        images = list(dict.fromkeys(kwargs.pop("images", []) + response.css(".carrousel__item .picture__image::attr(src)").getall()))

        interior = response.css("[aria-describedby='tooltip-listing-features-interior']::text").get("").strip()
        energy_label = response.css("[class*='listing-features__description--energy-label'] .listing-features__main-description::text").get("").strip()
        home_type = response.css(".listing-features__description--dwelling_type .listing-features__main-description::text").get("").strip()
        construction_year = response.css(".listing-features__description--construction_period .listing-features__main-description::text").get("").strip()
        floor = response.css(".listing-features__description--story_number .listing-features__main-description::text").get("").strip()

        yield {
            **kwargs,
            "city": self.city_name,
            "interior": interior,
            "description": description,
            "images": images,
            "energy_label": energy_label,
            "property_type": home_type,
            "construction_year": construction_year,
            "floor": floor,
        }
