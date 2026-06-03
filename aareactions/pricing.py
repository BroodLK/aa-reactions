# Standard Library
from decimal import Decimal
from functools import lru_cache

# Third Party
from allianceauth.services.hooks import get_extension_logger
import requests

# Django
from django.utils import timezone

# aareactions
from aareactions import app_settings
from aareactions.models import EveTypePrice


logger = get_extension_logger(__name__)

ZERO_PRICE_TUPLE = (
    Decimal("0"),
    Decimal("0"),
    Decimal("0"),
    Decimal("0"),
)


def _clean_item_ids(item_ids):
    cleaned_ids = []
    seen_ids = set()

    for item_id in item_ids or []:
        try:
            numeric_id = int(item_id)
        except (TypeError, ValueError):
            continue

        if numeric_id <= 0 or numeric_id in seen_ids:
            continue

        seen_ids.add(numeric_id)
        cleaned_ids.append(numeric_id)

    return cleaned_ids


def _decimal_or_zero(value):
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def is_zero_price_tuple(prices):
    return tuple(prices or ZERO_PRICE_TUPLE) == ZERO_PRICE_TUPLE


def _janice_headers():
    return {
        "Content-Type": "text/plain",
        "X-ApiKey": app_settings.AAREACTIONS_PRICE_JANICE_API_KEY,
        "accept": "application/json",
    }


@lru_cache(maxsize=1)
def valid_janice_api_key():
    api_key = app_settings.AAREACTIONS_PRICE_JANICE_API_KEY or ""
    if not api_key:
        return False

    try:
        response = requests.get(
            "https://janice.e-351.com/api/rest/v2/markets",
            headers=_janice_headers(),
            timeout=app_settings.AAREACTIONS_PRICE_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        return not (isinstance(payload, dict) and "status" in payload)
    except requests.RequestException as exc:
        logger.warning("Janice API key validation failed: %s", exc)
        return False
    except ValueError as exc:
        logger.warning("Janice API key validation returned invalid JSON: %s", exc)
        return False


def _use_janice():
    return app_settings.AAREACTIONS_PRICE_METHOD == "Janice" and valid_janice_api_key()


def _fetch_janice_price(item_id):
    try:
        response = requests.get(
            "https://janice.e-351.com/api/rest/v2/pricer/{0}".format(int(item_id)),
            headers=_janice_headers(),
            timeout=app_settings.AAREACTIONS_PRICE_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        node = response.json()

        return (
            _decimal_or_zero(node["immediatePrices"]["buyPrice5DayMedian"]),
            _decimal_or_zero(node["immediatePrices"]["sellPrice5DayMedian"]),
            _decimal_or_zero(node["top5AveragePrices"]["buyPrice5DayMedian"]),
            _decimal_or_zero(node["top5AveragePrices"]["sellPrice5DayMedian"]),
        )
    except requests.RequestException as exc:
        logger.error("Janice price fetch failed for %s: %s", item_id, exc)
    except (KeyError, TypeError, ValueError) as exc:
        logger.error("Janice payload parse failed for %s: %s", item_id, exc)

    return ZERO_PRICE_TUPLE


def _fetch_fuzzwork_prices(item_ids):
    price_map = {int(item_id): ZERO_PRICE_TUPLE for item_id in item_ids}
    if not item_ids:
        return price_map

    try:
        response = requests.get(
            "https://market.fuzzwork.co.uk/aggregates/",
            params={
                "types": ",".join(str(item_id) for item_id in item_ids),
                "station": app_settings.AAREACTIONS_PRICE_SOURCE_ID,
            },
            timeout=app_settings.AAREACTIONS_PRICE_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        logger.error("Fuzzwork price fetch failed for %s items: %s", len(item_ids), exc)
        return price_map
    except ValueError as exc:
        logger.error("Fuzzwork returned invalid JSON for %s items: %s", len(item_ids), exc)
        return price_map

    for item_id in item_ids:
        node = payload.get(str(item_id), {})
        if not node:
            continue

        try:
            price_map[int(item_id)] = (
                _decimal_or_zero(node["buy"]["max"]),
                _decimal_or_zero(node["sell"]["min"]),
                _decimal_or_zero(node["buy"]["percentile"]),
                _decimal_or_zero(node["sell"]["percentile"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("Fuzzwork payload parse failed for %s: %s", item_id, exc)

    return price_map


def fetch_price_map(item_ids):
    cleaned_ids = _clean_item_ids(item_ids)
    if not cleaned_ids:
        return {}

    if _use_janice():
        return {int(item_id): _fetch_janice_price(int(item_id)) for item_id in cleaned_ids}

    return _fetch_fuzzwork_prices(cleaned_ids)


def _fetch_prices(item_id):
    item_prices = fetch_price_map([item_id])
    return item_prices.get(int(item_id), ZERO_PRICE_TUPLE)


def refresh_prices(item_id):
    buy, sell, buy_average, sell_average = _fetch_prices(item_id)
    obj, _ = EveTypePrice.objects.get_or_create(eve_type_id=item_id)
    obj.buy = buy
    obj.sell = sell
    obj.buy_average = buy_average
    obj.sell_average = sell_average
    obj.updated = timezone.now()
    obj.save(update_fields=["buy", "sell", "buy_average", "sell_average", "updated"])
    return obj


def get_or_create_prices(item_id):
    if not isinstance(item_id, int) or item_id <= 0:
        obj, _ = EveTypePrice.objects.get_or_create(
            eve_type_id=item_id,
            defaults={"buy": 0, "sell": 0, "buy_average": 0, "sell_average": 0, "updated": timezone.now()},
        )
        return obj

    try:
        return EveTypePrice.objects.get(eve_type_id=item_id)
    except EveTypePrice.DoesNotExist:
        buy, sell, buy_average, sell_average = _fetch_prices(item_id)
        return EveTypePrice.objects.create(
            eve_type_id=item_id,
            buy=buy,
            sell=sell,
            buy_average=buy_average,
            sell_average=sell_average,
            updated=timezone.now(),
        )


def get_npc_price(item_id):
    try:
        return EveTypePrice.objects.get(eve_type_id=item_id)
    except EveTypePrice.DoesNotExist:
        logger.error("Price row missing for item %s.", item_id)
        return None


def resolve_price_value(item_id, basis):
    row = get_or_create_prices(item_id)
    if basis == "buy":
        return row.buy if app_settings.AAREACTIONS_PRICE_INSTANT else row.buy_average
    return row.sell if app_settings.AAREACTIONS_PRICE_INSTANT else row.sell_average
