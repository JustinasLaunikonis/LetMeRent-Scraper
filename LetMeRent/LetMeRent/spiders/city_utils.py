import re
import datetime


DEFAULT_CITY = "Emmen"
DEFAULT_COUNTRY = "Netherlands"


# Month names (and the common short forms) mapped to their number.
# Used by normalize_availability() to read dates like "1 sep 2026" or "June 1".
MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


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


def guess_year(month, day):
    # Some sites give a date without a year, like "1 September".
    # We pick the next time that day happens: this year if it is still
    # coming up, otherwise next year.
    today = datetime.date.today()
    year = today.year
    candidate = datetime.date(year, month, day)
    if candidate < today:
        year = year + 1
    return year


def build_date(year, month, day):
    # Turn the numbers into a clean "YYYY-MM-DD" string.
    # Returns "" when the numbers are not a real calendar date.
    try:
        real_date = datetime.date(year, month, day)
    except ValueError:
        return ""
    return real_date.isoformat()


def normalize_availability(text=None):
    # Each website writes the move-in date differently, for example:
    #   Kamernet:        "1 sep 2026"
    #   HousingAnywhere: "1 September"        (no year)
    #   Funda:           "Available on 6/16/2026"   (month/day/year)
    #   Huurwoningen:    "From 01-07-2026"          (day-month-year)
    #   iRentalize:      "June 1, 2026"
    # This helper turns all of them into one universal format, "YYYY-MM-DD", so
    # we can sort and compare move-in dates from every source the same way.
    # Phrases that mean "right away" become "Immediately".
    # Returns "" when there is nothing usable.
    if not text:
        return ""

    cleaned = str(text).strip()
    lowered = cleaned.lower()

    # "Available now", "Per direct" and "Immediately" all mean the same thing.
    if "immediat" in lowered or "now" in lowered or "direct" in lowered or "asap" in lowered:
        return "Immediately"

    # Look for a 4-digit year anywhere in the text (it may be missing).
    year_match = re.search(r"(\d{4})", cleaned)

    # 1) A text month written as "<day> <month>", like "1 sep 2026" or "1 September".
    day_month = re.search(r"(\d{1,2})\s+([A-Za-z]+)", cleaned)
    if day_month and day_month.group(2).lower() in MONTHS:
        day = int(day_month.group(1))
        month = MONTHS[day_month.group(2).lower()]
        if year_match:
            year = int(year_match.group(1))
        else:
            year = guess_year(month, day)
        return build_date(year, month, day)

    # 2) A text month written as "<month> <day>", like "June 1, 2026".
    month_day = re.search(r"([A-Za-z]+)\s+(\d{1,2})", cleaned)
    if month_day and month_day.group(1).lower() in MONTHS:
        month = MONTHS[month_day.group(1).lower()]
        day = int(month_day.group(2))
        if year_match:
            year = int(year_match.group(1))
        else:
            year = guess_year(month, day)
        return build_date(year, month, day)

    # 3) A numeric date with slashes. Funda uses American month/day/year,
    #    like "6/16/2026".
    slash = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", cleaned)
    if slash:
        month = int(slash.group(1))
        day = int(slash.group(2))
        year = int(slash.group(3))
        return build_date(year, month, day)

    # 4) A numeric date with dashes or dots. Huurwoningen uses Dutch
    #    day-month-year, like "01-07-2026".
    dash = re.search(r"(\d{1,2})[-.](\d{1,2})[-.](\d{4})", cleaned)
    if dash:
        day = int(dash.group(1))
        month = int(dash.group(2))
        year = int(dash.group(3))
        return build_date(year, month, day)

    only_letters = re.sub(r"[^a-z]", "", lowered)
    if only_letters == "available" or only_letters == "availablefrom":
        return "Immediately"

    # Nothing matched a date, so keep the original text.
    return cleaned
