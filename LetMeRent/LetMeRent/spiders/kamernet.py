import scrapy
import re


class KamernetSpider(scrapy.Spider):
    name = "kamernet"
    allowed_domains = ["kamernet.nl"]

    def __init__(self, city=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.city = (city or "emmen").lower().replace(" ", "-")
        self.start_urls = [f"https://kamernet.nl/en/for-rent/properties-{self.city}"]

    def parse(self, response, page=1, **kwargs):
        cards = response.css("a.SearchResultCard_root__hSxn3")

        for card in cards:
            href = card.attrib.get("href", "")
            url = f"https://kamernet.nl{href}" if href else ""
            image = card.css("img::attr(src)").get("")
            street = card.css(".SearchResultCard_contentRow__VZIJY span.CommonStyles_whiteSpaceNoWrap__wYjK1::text").get("").replace(",", "").strip()
            city = card.css(".SearchResultCard_contentRow__VZIJY span.MuiTypography-noWrap::text").get("").strip()

            details = card.css(".SearchResultCard_contentRow__VZIJY + .SearchResultCard_contentRow__VZIJY p::text").getall()
            size_raw = details[0].strip() if len(details) > 0 else ""
            size_match = re.search(r"\d+", size_raw)
            living_area = size_match.group() if size_match else ""
            furnished = details[1].strip() if len(details) > 1 else ""
            property_type = details[2].strip() if len(details) > 2 else ""

            available_from_raw = card.css(".SearchResultCard_contentRow__VZIJY p::text").getall()
            availability = next((t.strip().removeprefix("From").strip() for t in available_from_raw if "From" in t), "")

            raw_price = card.css("span.MuiTypography-h5::text").get("").strip()
            price_match = re.search(r"\d+", raw_price.replace(".", "").replace(",", ""))
            price = price_match.group() if price_match else ""

            price_type = card.css(".SearchResultCard_contentRow__VZIJY p.MuiTypography-body2::text").getall()
            price_label = next((t.strip() for t in price_type if "month" in t or "week" in t), "")

            if url:
                yield scrapy.Request(
                    url=url,
                    callback=self.parse_detail,
                    cb_kwargs={
                        "url": url,
                        "title": street,
                        "images": [image] if image else [],
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

        next_btn = response.css("button[aria-label='Go to next page']")

        if cards and next_btn and "disabled" not in next_btn.attrib:
            yield scrapy.Request(
                url=f"https://kamernet.nl/en/for-rent/properties-{self.city}?pageNo={page + 1}",
                callback=self.parse,
                cb_kwargs={"page": page + 1},
            )

    def parse_detail(self, response, **kwargs):
        description = " ".join(
            t.strip() for t in response.css("section.About_root__a4NUR pre p::text").getall() if t.strip()
        )

        amenities = response.css("section.Details_root__6__Gy .Details_gridItem__ids4p p.MuiTypography-body1::text").getall()

        cost_rows = response.css("section.RentalCosts_root__mUggN .RentalCosts_cardRow__RilZB")
        deposit_raw = ""
        additional_costs = ""
        for row in cost_rows:
            label = row.css("p::text").get("").strip()
            value = row.css("h6::text").get("").strip()
            if "Deposit" in label:
                deposit_raw = value
            elif "Additional" in label:
                additional_costs = value

        deposit_match = re.search(r"\d+", deposit_raw.replace(".", "").replace(",", ""))
        deposit = deposit_match.group() if deposit_match else ""

        additional_costs_match = re.search(r"\d+", additional_costs.replace(".", "").replace(",", ""))
        additional_costs = additional_costs_match.group() if additional_costs_match else ""

        rental_period = response.css(
            "section.Overview_root__CNI03 .PropertyDetails_row___QmRn p.MuiTypography-body4::text"
        ).getall()
        rental_period = rental_period[1] if len(rental_period) > 1 else (rental_period[0] if rental_period else "")

        tenant_rows = response.css("section.IdealTenant_root__TS7M8 .IdealTenant_row__U4412")
        ideal_tenant = {}
        for row in tenant_rows:
            texts = row.css("p::text").getall()
            if len(texts) == 2:
                key, val = texts[0].strip(), texts[1].strip()
                if key == "Number of tenants":
                    m = re.search(r"\d+", val)
                    val = m.group() if m else val
                elif key == "Age":
                    val = re.sub(r"\s*years$", "", val).strip()
                ideal_tenant[key] = val

        landlord_name = response.css("section.LandlordInfo_root__1KSuS h6.MuiTypography-subtitle1::text").get("").strip()
        landlord_type = response.css(".LandlordProfile_status___CzI5 p::text").get("").strip()

        posted = response.css("section.Header_root__RO9u9 .Header_row__cNlOA p.MuiTypography-body3::text").get("").strip()

        yield {
            **kwargs,
            "description": description,
            "amenities": amenities,
            "deposit": deposit,
            "additional_costs": additional_costs,
            "rental_period": rental_period,
            "ideal_tenant": ideal_tenant,
            "landlord_name": landlord_name,
            "landlord_type": landlord_type,
            "posted": posted,
        }
