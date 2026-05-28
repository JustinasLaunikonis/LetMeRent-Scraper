import re
from numbers import Number


def price_value(value):
    if value is None or value == "":
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, Number):
        return int(value)

    text = str(value).strip()
    if not text:
        return None

    digits = re.sub(r"[^\d]", "", text)
    if not digits:
        return None

    return int(digits)


def normalized_text(value):
    if value is None:
        return None

    text = str(value).strip().lower()
    return text or None
