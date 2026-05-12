import scrapy


class KamernetSpider(scrapy.Spider):
    name = "kamernet"
    allowed_domains = ["kamernet.nl"]
    start_urls = ["https://www.kamernet.nl/huren/huurwoningen-"]

    def __init__(self, city=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # default city
        self.city = (city or "emmen").lower().replace(" ", "-")

    def start_requests(self):
        url = f"https://www.kamernet.nl/huren/huurwoningen-{self.city}"
        yield scrapy.Request(url=url, callback=self.parse)

    def parse(self, response):
        cards = response.css("a.SearchResultCard_root__hSxn3")

        for card in cards:
            href = card.css("::attr(href)").get()
            street = card.css("div.SearchResultCard_contentRow__VZIJY span::text").get()
            city = card.css("span.MuiTypography-noWrap::text").get()
            details = card.css("div.SearchResultCard_contentRow__VZIJY p::text").getall()

            size = details[0] if len(details) > 0 else None
            furnished = details[1] if len(details) > 1 else None
            property_type = details[2] if len(details) > 2 else None
            availability = details[3] if len(details) > 3 else None
            price_label = details[-1] if len(details) > 0 else None

            price = card.css("span.MuiTypography-h5::text").get()
            image = card.css("img::attr(src)").get()
            image_alt = card.css("img::attr(alt)").get()

            yield {
                "street": street,
                "city": city,
                "size": size,
                "furnished": furnished,
                "property_type": property_type,
                "availability": availability,
                "price": price,
                "price_label": price_label,
                "image": image,
                "image_alt": image_alt,
                "url": response.urljoin(href),
            }