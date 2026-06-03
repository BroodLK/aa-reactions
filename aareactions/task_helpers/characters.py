# Standard Library
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

# Third Party
from allianceauth.services.hooks import get_extension_logger

# Django
from django.db import transaction
from django.utils import timezone

# aareactions
from aareactions.models import CharacterReactions, CharacterStandings, CharacterToken


logger = get_extension_logger(__name__)


REACTION_SKILL_ID = 45746
ACCOUNTING_SKILL_ID = 16622
BROKER_RELATIONS_SKILL_ID = 3446
REPROCESSING_SKILL_ID = 3385
REPROCESSING_EFFICIENCY_SKILL_ID = 3389
UBIQUITOUS_MOON_PROCESSING_SKILL_ID = 46152
COMMON_MOON_PROCESSING_SKILL_ID = 46153
UNCOMMON_MOON_PROCESSING_SKILL_ID = 46154
RARE_MOON_PROCESSING_SKILL_ID = 46155
EXCEPTIONAL_MOON_PROCESSING_SKILL_ID = 46156
SCRAP_METAL_PROCESSING_SKILL_ID = 12196


def get_character_token(character_id):
    return CharacterToken.objects.filter(character_id=character_id).select_related("character").first()


def _response_value(entry, *names):
    for name in names:
        if isinstance(entry, dict) and name in entry:
            return entry.get(name)
        if hasattr(entry, name):
            return getattr(entry, name)
    return None


def _as_skill_map(data):
    skills_list = _response_value(data, "skills") or []
    skill_map = {}

    for skill in skills_list:
        skill_id = _response_value(skill, "skill_id")
        if skill_id is None:
            continue
        skill_map[int(skill_id)] = int(_response_value(skill, "active_skill_level") or 0)

    return skill_map


def _as_standing(value):
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def update_character_skills_record(character_id, data):
    token = get_character_token(character_id)
    if not token:
        logger.debug("No CharacterToken found for %s while updating skills.", character_id)
        return False

    skill_map = _as_skill_map(data)

    with transaction.atomic():
        reactions, _ = CharacterReactions.objects.select_for_update().get_or_create(character=token)
        reactions.reaction_skill_level = skill_map.get(REACTION_SKILL_ID, 0)
        reactions.accounting_level = skill_map.get(ACCOUNTING_SKILL_ID, 0)
        reactions.broker_relations_skill_level = skill_map.get(BROKER_RELATIONS_SKILL_ID, 0)
        reactions.reprocessing_level = skill_map.get(REPROCESSING_SKILL_ID, 0)
        reactions.reprocessing_efficiency = skill_map.get(REPROCESSING_EFFICIENCY_SKILL_ID, 0)
        reactions.ubiquitous_moon_processing_level = skill_map.get(
            UBIQUITOUS_MOON_PROCESSING_SKILL_ID, 0
        )
        reactions.common_moon_processing_level = skill_map.get(COMMON_MOON_PROCESSING_SKILL_ID, 0)
        reactions.uncommon_moon_processing_level = skill_map.get(UNCOMMON_MOON_PROCESSING_SKILL_ID, 0)
        reactions.rare_moon_processing_level = skill_map.get(RARE_MOON_PROCESSING_SKILL_ID, 0)
        reactions.exceptional_moon_processing_level = skill_map.get(
            EXCEPTIONAL_MOON_PROCESSING_SKILL_ID, 0
        )
        reactions.scrap_metal_processing_level = skill_map.get(SCRAP_METAL_PROCESSING_SKILL_ID, 0)
        reactions.last_update = timezone.now()
        reactions.save(
            update_fields=[
                "reaction_skill_level",
                "accounting_level",
                "broker_relations_skill_level",
                "reprocessing_level",
                "reprocessing_efficiency",
                "ubiquitous_moon_processing_level",
                "common_moon_processing_level",
                "uncommon_moon_processing_level",
                "rare_moon_processing_level",
                "exceptional_moon_processing_level",
                "scrap_metal_processing_level",
                "last_update",
            ]
        )

    return True


def update_character_standings_record(character_id, rows):
    token = get_character_token(character_id)
    if not token:
        logger.debug("No CharacterToken found for %s while updating standings.", character_id)
        return False

    now = timezone.now()
    existing_rows = CharacterStandings.objects.filter(character=token).in_bulk(field_name="entity_id")
    to_create = []
    to_update = []
    seen = set()

    for row in rows or []:
        entity_id = int(_response_value(row, "from_id", "fromID") or 0)
        entity_type = str(_response_value(row, "from_type", "fromType") or "")
        standing = _as_standing(_response_value(row, "standing", "Standing"))

        if entity_id <= 0:
            continue

        seen.add(entity_id)
        current_row = existing_rows.get(entity_id)

        if current_row is None:
            to_create.append(
                CharacterStandings(
                    character=token,
                    entity_id=entity_id,
                    entity_type=entity_type,
                    standing=standing,
                    last_update=now,
                )
            )
            continue

        current_row.entity_type = entity_type
        current_row.standing = standing
        current_row.last_update = now
        to_update.append(current_row)

    with transaction.atomic():
        if to_create:
            CharacterStandings.objects.bulk_create(to_create, batch_size=500)
        if to_update:
            CharacterStandings.objects.bulk_update(
                to_update,
                fields=["entity_type", "standing", "last_update"],
                batch_size=500,
            )
        CharacterStandings.objects.filter(character=token).exclude(entity_id__in=seen).delete()

    return True
