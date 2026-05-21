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
