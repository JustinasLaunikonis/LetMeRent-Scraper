DEFAULT_CITY = "Emmen"
DEFAULT_COUNTRY = "Netherlands"


def clean_city(city=None):
    value = city or DEFAULT_CITY
    value = value.split("--", 1)[0]
    value = value.replace("-", " ")
    return " ".join(value.split())


def city_slug(city=None):
    return clean_city(city).lower().replace(" ", "-")


def city_title(city=None):
    return clean_city(city).title()


def housinganywhere_city(city=None, country=DEFAULT_COUNTRY):
    return f"{city_title(city).replace(' ', '-')}--{country}"


def normalize_status(text=None):
    # Each website writes the listing status differently, for example:
    # "For rent", "RENTED" or "Under option".
    # This helper function turns makes them universal, so we can filter and sort on them later
    # Returns "" when there is nothing to read
    if not text:
        return ""

    lowered = str(text).lower()

    # Check "reserved" style words first, because some sites say things
    # like "Rented under reservation" which is basicaly a reservation
    if "reserv" in lowered or "under option" in lowered or "under offer" in lowered:
        return "Reserved"
    if "rented" in lowered or "verhuurd" in lowered:
        return "Rented"
    if "available" in lowered or "for rent" in lowered or "te huur" in lowered:
        return "Available"

    # Keep the original text.
    return text
