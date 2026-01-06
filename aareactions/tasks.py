# aareactions/tasks.py
"""App Tasks"""

import logging
from typing import List
from celery import shared_task

from django.db import transaction
from django.utils import timezone

from eveuniverse.models import EveType

from .models import EveTypePrice, CharacterToken, CharacterReactions, CharacterStandings
from .providers import get_character_skills, get_character_standings
from .pricing import _fetch_prices

# Force logs to console for Celery worker/beat
root_logger = logging.getLogger()
if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
    root_logger.addHandler(logging.StreamHandler())
root_logger.setLevel(logging.DEBUG)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)




@shared_task(bind=True, name="aareactions.seed_all_price_rows")
def seed_all_price_rows(self) -> dict:
    ids: List[int] = list(EveType.objects.values_list("id", flat=True))
    existing = set(EveTypePrice.objects.filter(eve_type_id__in=ids).values_list("eve_type_id", flat=True))
    to_create = [EveTypePrice(eve_type_id=i) for i in ids if i not in existing]
    created = 0
    if to_create:
        with transaction.atomic():
            EveTypePrice.objects.bulk_create(to_create, ignore_conflicts=True, batch_size=2000)
            created = len(to_create)
    logger.info("seed_all_price_rows: created=%s total_types=%s", created, len(ids))
    return {"created": created, "total_types": len(ids)}


@shared_task(bind=True, name="aareactions.refresh_all_prices")
def refresh_all_prices(self, chunk_size: int = 1000) -> dict:
    logger.info("refresh_all_prices: started chunk_size=%s", chunk_size)
    ids: List[int] = list(EveType.objects.values_list("id", flat=True))
    updated = 0
    skipped_zero = 0
    failed = 0

    for i in range(0, len(ids), chunk_size):
        batch = ids[i : i + chunk_size]
        logger.info("refresh_all_prices: processing %s..%s (of %s)", i, i + len(batch) - 1, len(ids))
        for tid in batch:
            try:
                buy, sell, buy_avg, sell_avg = _fetch_prices(int(tid))
                if buy == 0 and sell == 0 and buy_avg == 0 and sell_avg == 0:
                    skipped_zero += 1
                    logger.debug("refresh_all_prices: skip %s (all zeros)", tid)
                    continue
                EveTypePrice.objects.update_or_create(
                    eve_type_id=tid,
                    defaults={"buy": buy, "sell": sell, "buy_average": buy_avg, "sell_average": sell_avg},
                )
                updated += 1
                if updated % 500 == 0:
                    logger.info("refresh_all_prices: updated so far=%s", updated)
            except Exception as exc:
                failed += 1
                logger.exception("refresh_all_prices: fail for %s: %s", tid, exc)

    logger.info(
        "refresh_all_prices: done updated=%s skipped_zero=%s failed=%s total=%s",
        updated,
        skipped_zero,
        failed,
        len(ids),
    )
    return {"updated": updated, "skipped_zero": skipped_zero, "failed": failed, "total": len(ids)}

@shared_task(bind=True, name="aareactions.update_all_character_skills")
def update_all_character_skills(self):
    ids = list(CharacterToken.objects.values_list("character_id", flat=True))
    for cid in ids:
        update_character_skills.delay(character_id=int(cid))

@shared_task(bind=True, name="aareactions.update_character_skills")
def update_character_skills(self, character_id: int):
    token = CharacterToken.objects.filter(character_id=character_id).select_related("character").first()
    if not token:
        return
    data = get_character_skills(character_id)
    skills_list = (getattr(data, "skills", None) or data.get("skills", []) or [])
    by_id = {int(getattr(s, "skill_id", s.get("skill_id"))): int(getattr(s, "active_skill_level", s.get("active_skill_level", 0))) for s in skills_list}

    reactions = by_id.get(45746, 0)
    accounting = by_id.get(16622, 0)
    broker_relations = by_id.get(3446, 0)
    reprocessing_level = by_id.get(3385, 0)
    reprocessing_efficiency = by_id.get(3389, 0)
    ubiquitous_moon_processing_level = by_id.get(46152, 0)
    common_moon_processing_level = by_id.get(46153, 0)
    uncommon_moon_processing_level = by_id.get(46154, 0)
    rare_moon_processing_level = by_id.get(46155, 0)
    exceptional_moon_processing_level = by_id.get(46156, 0)
    smp_level = by_id.get(12196, 0)

    with transaction.atomic():
        cr, _ = CharacterReactions.objects.select_for_update().get_or_create(character=token)
        cr.reaction_skill_level = reactions
        cr.accounting_level = accounting
        cr.broker_relations_skill_level = broker_relations
        cr.reprocessing_level = reprocessing_level
        cr.reprocessing_efficiency = reprocessing_efficiency
        cr.ubiquitous_moon_processing_level = ubiquitous_moon_processing_level
        cr.common_moon_processing_level = common_moon_processing_level
        cr.uncommon_moon_processing_level = uncommon_moon_processing_level
        cr.rare_moon_processing_level = rare_moon_processing_level
        cr.exceptional_moon_processing_level = exceptional_moon_processing_level
        cr.scrap_metal_processing_level = smp_level
        cr.last_update = timezone.now()
        cr.save(update_fields=[
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
        ])

@shared_task(bind=True, name="aareactions.update_all_character_standings")
def update_all_character_standings(self):
    ids = list(CharacterToken.objects.values_list("character_id", flat=True))
    for cid in ids:
        update_character_standings.delay(character_id=int(cid))

@shared_task(bind=True, name="aareactions.update_character_standings")
def update_character_standings(self, character_id: int):
    token = CharacterToken.objects.filter(character_id=character_id).select_related("character").first()
    if not token:
        return
    rows = get_character_standings(character_id) or []
    now = timezone.now()
    to_upsert = []
    seen = set()

    for r in rows:
        entity_id = int(getattr(r, "from_id", getattr(r, "fromID", 0)) or 0)
        standing = int(round(float(getattr(r, "standing", getattr(r, "Standing", 0)) or 0)))
        entity_type = str(getattr(r, "from_type", getattr(r, "fromType", "")) or "")
        if entity_id <= 0:
            continue
        seen.add(entity_id)
        to_upsert.append((entity_id, entity_type, standing))

    with transaction.atomic():
        if to_upsert:
            for eid, etype, st in to_upsert:
                CharacterStandings.objects.update_or_create(
                    character=token,
                    entity_id=eid,
                    defaults={"entity_type": etype, "standing": st, "last_update": now},
                )
        CharacterStandings.objects.filter(character=token).exclude(entity_id__in=seen).delete()
