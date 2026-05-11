import scrapy


class HousinganywhereSpider(scrapy.Spider):
    name = "housinganywhere"
    allowed_domains = ["housinganywhere.com"]
    start_urls = ["https://housinganywhere.com/s/"]

    def __init__(self, city=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.city = city or "Emmen--Netherlands"

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
            availability = card.css('[data-test-locator="ListingCard/Availability"] span::text').get()
            href = card.css("::attr(href)").get()

            images = card.css('[data-test-locator="ListingCardPhotoGallery/Photo"]::attr(src)').getall()

            # fallback: some images only have srcset
            srcset_images = card.css('[data-test-locator="ListingCardPhotoGallery/Photo"]::attr(srcset)').getall()

            yield {
                "title": title,
                "price": price,
                "price_label": price_label,
                "size": size,
                "housemates": housemates,
                "availability": availability,
                "url": response.urljoin(href),
                "images": images,
                "srcset_images": srcset_images,
            }
