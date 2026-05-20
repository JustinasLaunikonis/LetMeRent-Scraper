import re
import json
import scrapy


LISTING_SELECTOR = '[data-testid="listingDetailsAddress"]'


class FundaSpider(scrapy.Spider):
    name = "funda"
    allowed_domains = ["funda.nl"]

    def __init__(self, city=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.city = city or "emmen"

    def start_requests(self):
        yield scrapy.Request(self._search_url(1), callback=self.parse, cb_kwargs={"page": 1})

    def _search_url(self, page):
        return f'https://www.funda.nl/en/zoeken/koop?selected_area=["{self.city}"]&page={page}'

    def parse(self, response, page=1):
        listings = response.css(LISTING_SELECTOR)
        self.logger.info(f"Page {page}: found {len(listings)} listings")

        for address_link in listings:
            href = address_link.attrib.get("href", "")
            if href:
                yield response.follow(href, callback=self.parse_detail)

        if listings:
            yield scrapy.Request(self._search_url(page + 1), callback=self.parse, cb_kwargs={"page": page + 1})

    def _deref(self, arr, idx):
        if not isinstance(idx, int) or idx < 0 or idx >= len(arr):
            return None
        val = arr[idx]
        if isinstance(val, list):
            if val and isinstance(val[0], str) and val[0] in ("ShallowReactive", "Reactive", "Set"):
                return self._deref(arr, val[1]) if len(val) > 1 else None
            return [self._deref(arr, v) if isinstance(v, int) else v for v in val]
        if isinstance(val, dict):
            return {k: (self._deref(arr, v) if isinstance(v, int) else v) for k, v in val.items()}
        return val

    def _nuxt_listing(self, response):
        raw = response.css("script#__NUXT_DATA__::text").get("")
        if not raw:
            return {}
        try:
            arr = json.loads(raw)
            for item in arr:
                if isinstance(item, dict):
                    for k, v in item.items():
                        if k.startswith("cachedListingData"):
                            return self._deref(arr, v) or {}
        except Exception:
            pass
        return {}

    def parse_detail(self, response):
        listing = self._nuxt_listing(response)

        price_obj = listing.get("price") or {}
        fv = listing.get("featuresFastView") or {}
        desc_obj = listing.get("description") or {}
        addr = listing.get("address") or {}
        coords = listing.get("coordinates") or {}

        def digits(val):
            s = re.sub(r"[^\d]", "", str(val or ""))
            return int(s) if s else None

        def leading_int(val):
            m = re.match(r"[\d,\.]+", re.sub(r"^€\s*", "", val.strip()))
            if m:
                s = re.sub(r"[^\d]", "", m.group())
                return int(s) if s else val
            return val

        price = price_obj.get("numericPrice")
        living_area = digits(fv.get("livingArea"))
        plot_size = digits(fv.get("plotArea"))
        bedrooms = digits(fv.get("numberOfBedrooms"))
        energy_label = fv.get("energyLabel")
        description = (desc_obj.get("content") or "").strip()
        lat = coords.get("lat")
        lng = coords.get("lng")

        street = addr.get("addressTitle") or response.css("h1[data-global-id] span.block::text").get("").strip()
        postal_city = addr.get("addressSubtitle") or response.css("h1[data-global-id] .text-neutral-40::text").get("").strip()
        neighbourhood = (addr.get("neighborhood") or {}).get("name") or response.css("h1[data-global-id] a::text").get("").strip()

        features = {}
        for cat in response.css('[data-testid^="category-"]'):
            for dt, dd in zip(cat.css("dt"), cat.css("dd")):
                key = " ".join(dt.css("::text").getall()).strip()
                val = " ".join(dd.css("::text").getall()).strip()
                if key and val:
                    if val.startswith("€") or re.match(r"^\d", val):
                        features[key] = leading_int(val)
                    else:
                        features[key] = val

        agent_person = response.css("span.wrap-break-word::text").get("").strip()
        agent = response.css('h3 a[href*="/makelaar/"]::text').get("").strip()
        agent_url = response.css('h3 a[href*="/makelaar/"]::attr(href)').get("")
        phone_href = response.css('a[href^="tel:"]::attr(href)').get("")
        phone = phone_href.replace("tel:", "") if phone_href else ""
        image = response.css("#media .col-span-2 img::attr(src)").get("")

        yield {
            "url": response.url,
            "street": street,
            "postal_city": postal_city,
            "neighbourhood": neighbourhood,
            "lat": lat,
            "lng": lng,
            "price": price,
            "living_area": living_area,
            "plot_size": plot_size,
            "bedrooms": bedrooms,
            "energy_label": energy_label,
            "description": description,
            "agent_person": agent_person,
            "agent": agent,
            "agent_url": agent_url,
            "phone": phone,
            "image": image,
            "features": features,
        }