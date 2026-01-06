# pricing.py
import logging
from decimal import Decimal
from typing import Optional
import requests
from django.db.utils import Error
from django.utils import timezone
from .app_settings import (
    AAREACTIONS_PRICE_INSTANT,
    AAREACTIONS_PRICE_JANICE_API_KEY,
    AAREACTIONS_PRICE_METHOD,
    AAREACTIONS_PRICE_SOURCE_ID,
)
from .models import EveTypePrice

logger = logging.getLogger(__name__)


def valid_janice_api_key() -> bool:
    api_key = AAREACTIONS_PRICE_JANICE_API_KEY or ""
    if not api_key:
        logger.debug("valid_janice_api_key: empty API key")
        return False
    try:
        logger.debug("valid_janice_api_key: calling Janice markets endpoint")
        r = requests.get(
            "https://janice.e-351.com/api/rest/v2/markets",
            headers={"Content-Type": "text/plain", "X-ApiKey": api_key, "accept": "application/json"},
            timeout=20,
        )
        logger.debug("valid_janice_api_key: status_code=%s", r.status_code)
        r.raise_for_status()
        data = r.json()
        ok = not (isinstance(data, dict) and "status" in data)
        logger.debug("valid_janice_api_key: json_ok=%s", ok)
        return ok
    except Exception as e:
        logger.warning("valid_janice_api_key: request failed: %s", e)
        return False


def _fetch_prices(item_id: int) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    logger.debug("fetch_prices: start item_id=%s method=%s station=%s", item_id, AAREACTIONS_PRICE_METHOD, AAREACTIONS_PRICE_SOURCE_ID)
    if not isinstance(item_id, int) or item_id <= 0:
        logger.debug("fetch_prices: invalid item_id=%s", item_id)
        return (Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))

    buy = sell = buy_average = sell_average = Decimal("0")
    try:
        use_janice = AAREACTIONS_PRICE_METHOD == "Janice" and valid_janice_api_key()
        logger.debug("fetch_prices: use_janice=%s", use_janice)

        if use_janice:
            url = f"https://janice.e-351.com/api/rest/v2/pricer/{item_id}"
            headers = {"Content-Type": "text/plain", "X-ApiKey": AAREACTIONS_PRICE_JANICE_API_KEY, "accept": "application/json"}
            logger.debug("fetch_prices: GET %s headers=%s", url, {"X-ApiKey": "***"})
            resp = requests.get(url, headers=headers, timeout=20)
            logger.debug("fetch_prices: janice status=%s", resp.status_code)
            resp.raise_for_status()
            node = resp.json()
            logger.debug("fetch_prices: janice payload keys=%s", list(node.keys()))
            buy = Decimal(str(node["immediatePrices"]["buyPrice5DayMedian"]))
            sell = Decimal(str(node["immediatePrices"]["sellPrice5DayMedian"]))
            buy_average = Decimal(str(node["top5AveragePrices"]["buyPrice5DayMedian"]))
            sell_average = Decimal(str(node["top5AveragePrices"]["sellPrice5DayMedian"]))
        else:
            url = "https://market.fuzzwork.co.uk/aggregates/"
            params = {"types": item_id, "station": AAREACTIONS_PRICE_SOURCE_ID}
            logger.debug("fetch_prices: GET %s params=%s", url, params)
            resp = requests.get(url, params=params, timeout=20)
            logger.debug("fetch_prices: fuzzwork status=%s", resp.status_code)
            resp.raise_for_status()
            data = resp.json()
            logger.debug("fetch_prices: fuzzwork keys=%s", list(data.keys())[:5])
            node = data.get(str(item_id), {})
            if not node:
                logger.warning("fetch_prices: fuzzwork missing node for %s", item_id)
            else:
                logger.debug("fetch_prices: fuzzwork node keys=%s", list(node.keys()))
                buy = Decimal(str(node["buy"]["max"]))
                sell = Decimal(str(node["sell"]["min"]))
                buy_average = Decimal(str(node["buy"]["percentile"]))
                sell_average = Decimal(str(node["sell"]["percentile"]))
    except requests.HTTPError as e:
        logger.error("fetch_prices: HTTP error for %s: %s body=%s", item_id, e, getattr(e.response, "text", ""))
    except KeyError as e:
        logger.error("fetch_prices: payload missing key %s for %s", e, item_id)
    except Exception as e:
        logger.error("fetch_prices: generic failure for %s: %s", item_id, e)

    logger.debug(
        "fetch_prices: result item_id=%s buy=%s sell=%s buy_avg=%s sell_avg=%s",
        item_id,
        buy,
        sell,
        buy_average,
        sell_average,
    )
    return buy, sell, buy_average, sell_average


def refresh_prices(item_id: int) -> EveTypePrice:
    logger.debug("refresh_prices: item_id=%s", item_id)
    buy, sell, buy_average, sell_average = _fetch_prices(item_id)
    obj, created = EveTypePrice.objects.get_or_create(eve_type_id=item_id)
    logger.debug("refresh_prices: row %s (created=%s)", obj.eve_type_id, created)
    obj.buy = buy
    obj.sell = sell
    obj.buy_average = buy_average
    obj.sell_average = sell_average
    obj.updated = timezone.now()
    obj.save(update_fields=["buy", "sell", "buy_average", "sell_average", "updated"])
    logger.debug("refresh_prices: saved item_id=%s", item_id)
    return obj


def get_or_create_prices(item_id: int) -> EveTypePrice:
    logger.debug("get_or_create_prices: item_id=%s", item_id)
    if not isinstance(item_id, int) or item_id <= 0:
        obj, _ = EveTypePrice.objects.get_or_create(
            eve_type_id=item_id,
            defaults={"buy": 0, "sell": 0, "buy_average": 0, "sell_average": 0, "updated": timezone.now()},
        )
        logger.debug("get_or_create_prices: returned zero row for invalid id=%s", item_id)
        return obj
    try:
        obj = EveTypePrice.objects.get(eve_type_id=item_id)
        logger.debug("get_or_create_prices: cache hit for %s", item_id)
        return obj
    except EveTypePrice.DoesNotExist:
        logger.debug("get_or_create_prices: cache miss for %s, fetching ...", item_id)
        buy, sell, buy_average, sell_average = _fetch_prices(item_id)
        updated = timezone.now()
        obj = EveTypePrice.objects.create(
            eve_type_id=item_id,
            buy=buy,
            sell=sell,
            buy_average=buy_average,
            sell_average=sell_average,
            updated=updated,
        )
        logger.debug("get_or_create_prices: created row for %s", item_id)
        return obj


def get_npc_price(item_id: int) -> Optional[EveTypePrice]:
    logger.debug("get_npc_price: item_id=%s", item_id)
    try:
        return EveTypePrice.objects.get(eve_type_id=item_id)
    except EveTypePrice.DoesNotExist:
        logger.error("get_npc_price: missing for %s", item_id)
        return None
    except Exception as e:
        logger.error("get_npc_price: error for %s: %s", item_id, e)
        return None


def resolve_price_value(item_id: int, basis: str) -> Decimal:
    logger.debug("resolve_price_value: item_id=%s basis=%s", item_id, basis)
    row = get_or_create_prices(item_id)
    if basis == "buy":
        val = row.buy if AAREACTIONS_PRICE_INSTANT else row.buy_average
    else:
        val = row.sell if AAREACTIONS_PRICE_INSTANT else row.sell_average
    logger.debug("resolve_price_value: item_id=%s -> %s", item_id, val)
    return val
