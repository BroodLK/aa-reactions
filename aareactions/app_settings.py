"""App Settings"""

# Django
from django.conf import settings

AAREACTIONS_PRICE_METHOD = getattr(settings, "AAREACTIONS_PRICE_METHOD", "Fuzzwork")
AAREACTIONS_PRICE_SOURCE_ID = int(getattr(settings, "AAREACTIONS_PRICE_SOURCE_ID", 60003760))
AAREACTIONS_PRICE_JANICE_API_KEY = getattr(settings, "AAREACTIONS_PRICE_JANICE_API_KEY", "")
AAREACTIONS_PRICE_INSTANT = bool(getattr(settings, "AAREACTIONS_PRICE_INSTANT", True))
