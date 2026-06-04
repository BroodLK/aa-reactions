# Django
from django.db import transaction
from django.utils import timezone

# Alliance Auth
from allianceauth.services.hooks import get_extension_logger

# Alliance Auth (External Libs)
from eve_sde.models import ItemType as EveType

# aa-reactions
# aareactions
from aareactions import app_settings
from aareactions.models import EveTypePrice
from aareactions.pricing import fetch_price_map, is_zero_price_tuple

logger = get_extension_logger(__name__)


def chunk_ids(values, chunk_size):
    for index in range(0, len(values), chunk_size):
        yield values[index : index + chunk_size]


def seed_all_price_rows():
    eve_type_ids = list(EveType.objects.values_list("id", flat=True))
    existing_ids = set(EveTypePrice.objects.filter(eve_type_id__in=eve_type_ids).values_list("eve_type_id", flat=True))
    to_create = [EveTypePrice(eve_type_id=type_id) for type_id in eve_type_ids if type_id not in existing_ids]

    created = 0
    if to_create:
        with transaction.atomic():
            EveTypePrice.objects.bulk_create(
                to_create,
                ignore_conflicts=True,
                batch_size=app_settings.AAREACTIONS_PRICE_BATCH_SIZE,
            )
        created = len(to_create)

    return {"created": created, "total_types": len(eve_type_ids)}


def refresh_all_price_rows(chunk_size=None):
    batch_size = int(chunk_size or app_settings.AAREACTIONS_PRICE_BATCH_SIZE)
    eve_type_ids = list(EveType.objects.values_list("id", flat=True))
    updated = 0
    skipped_zero = 0
    failed = 0

    for batch_number, batch in enumerate(chunk_ids(eve_type_ids, batch_size), start=1):
        logger.info("Refreshing price batch %s containing %s types.", batch_number, len(batch))

        try:
            price_map = fetch_price_map(batch)
        except Exception:
            logger.exception("Bulk price refresh failed for batch %s.", batch_number)
            failed += len(batch)
            continue

        existing_rows = EveTypePrice.objects.in_bulk(batch, field_name="eve_type_id")
        batch_now = timezone.now()
        to_create = []
        to_update = []

        for type_id in batch:
            prices = price_map.get(int(type_id))
            if prices is None:
                failed += 1
                continue

            if is_zero_price_tuple(prices):
                skipped_zero += 1
                continue

            buy, sell, buy_average, sell_average = prices
            current_row = existing_rows.get(int(type_id))

            if current_row is None:
                to_create.append(
                    EveTypePrice(
                        eve_type_id=int(type_id),
                        buy=buy,
                        sell=sell,
                        buy_average=buy_average,
                        sell_average=sell_average,
                        updated=batch_now,
                    )
                )
            else:
                current_row.buy = buy
                current_row.sell = sell
                current_row.buy_average = buy_average
                current_row.sell_average = sell_average
                current_row.updated = batch_now
                to_update.append(current_row)

        with transaction.atomic():
            if to_create:
                EveTypePrice.objects.bulk_create(
                    to_create,
                    batch_size=app_settings.AAREACTIONS_PRICE_BATCH_SIZE,
                )
            if to_update:
                EveTypePrice.objects.bulk_update(
                    to_update,
                    fields=["buy", "sell", "buy_average", "sell_average", "updated"],
                    batch_size=app_settings.AAREACTIONS_PRICE_BATCH_SIZE,
                )

        updated += len(to_create) + len(to_update)

    return {
        "updated": updated,
        "skipped_zero": skipped_zero,
        "failed": failed,
        "total": len(eve_type_ids),
    }
