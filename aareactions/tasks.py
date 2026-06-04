"""Celery tasks for aareactions."""

# Third Party
from celery import shared_task

# Alliance Auth
from allianceauth.services.hooks import get_extension_logger

# aa-reactions
# aareactions
from aareactions import app_settings
from aareactions.models import CharacterToken
from aareactions.providers import get_character_skills, get_character_standings
from aareactions.task_helpers.characters import (
    update_character_skills_record,
    update_character_standings_record,
)
from aareactions.task_helpers.pricing import (
    refresh_all_price_rows,
)
from aareactions.task_helpers.pricing import seed_all_price_rows as seed_price_rows

logger = get_extension_logger(__name__)


@shared_task(bind=True, name="aareactions.seed_all_price_rows")
def seed_all_price_rows(self):
    result = seed_price_rows()
    logger.info(
        "Seeded %s missing price rows across %s item types.",
        result["created"],
        result["total_types"],
    )
    return result


@shared_task(bind=True, name="aareactions.refresh_all_prices")
def refresh_all_prices(self, chunk_size=None):
    result = refresh_all_price_rows(chunk_size=chunk_size or app_settings.AAREACTIONS_PRICE_BATCH_SIZE)
    logger.info(
        "Finished price refresh: updated=%s skipped_zero=%s failed=%s total=%s.",
        result["updated"],
        result["skipped_zero"],
        result["failed"],
        result["total"],
    )
    return result


@shared_task(bind=True, name="aareactions.update_all_character_skills")
def update_all_character_skills(self):
    character_ids = list(CharacterToken.objects.values_list("character_id", flat=True))
    for character_id in character_ids:
        update_character_skills.apply_async(kwargs={"character_id": int(character_id)})


@shared_task(bind=True, name="aareactions.update_character_skills")
def update_character_skills(self, character_id):
    data = get_character_skills(character_id)
    return update_character_skills_record(character_id, data)


@shared_task(bind=True, name="aareactions.update_all_character_standings")
def update_all_character_standings(self):
    character_ids = list(CharacterToken.objects.values_list("character_id", flat=True))
    for character_id in character_ids:
        update_character_standings.apply_async(kwargs={"character_id": int(character_id)})


@shared_task(bind=True, name="aareactions.update_character_standings")
def update_character_standings(self, character_id):
    rows = get_character_standings(character_id) or []
    return update_character_standings_record(character_id, rows)
