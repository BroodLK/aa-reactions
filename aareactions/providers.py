# Standard Library
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple

# Third Party
import requests

# Alliance Auth
from allianceauth.services.hooks import get_extension_logger
from esi.models import Token
from esi.openapi_clients import ESIClientProvider

# aa-reactions
# aareactions
from aareactions import __url__, __version__, app_settings
from aareactions.apps import ReactionsConfig

logger = get_extension_logger(__name__)

DEFAULT_REACTION_STRUCTURE_TYPE_IDS = {
    "medium": 35835,
    "large": 35836,
}
SECURITY_CLASS_BY_LOCATION = {
    "low": "LOW_SEC",
    "null": "NULL_SEC",
    "wh": "NULL_SEC",
}


class ReactionsEsiProvider(ESIClientProvider):
    """Small wrapper around django-esi OpenAPI access for this app."""

    def _get_token(self, character_id, scopes):
        return Token.get_token(character_id, scopes)

    def industry_systems_op(self):
        return self.client.Industry.GetIndustrySystems()

    def industry_systems(self):
        return self.industry_systems_op().results()

    def station_information_op(self, station_id):
        return self.client.Universe.GetUniverseStationsStationId(station_id=station_id)

    def station_information(self, station_id):
        return self.station_information_op(station_id).results()

    def character_standings_op(self, character_id):
        token = self._get_token(character_id, app_settings.AAREACTIONS_CHARACTER_STANDINGS_SCOPES)
        return self.client.Character.GetCharactersCharacterIdStandings(
            character_id=character_id,
            token=token,
        )

    def character_standings(self, character_id):
        return self.character_standings_op(character_id).results()

    def character_skills_op(self, character_id):
        token = self._get_token(character_id, app_settings.AAREACTIONS_CHARACTER_SKILLS_SCOPES)
        return self.client.Skills.GetCharactersCharacterIdSkills(
            character_id=character_id,
            token=token,
        )

    def character_skills(self, character_id):
        return self.character_skills_op(character_id).results()


esi = ReactionsEsiProvider(
    compatibility_date=app_settings.AAREACTIONS_ESI_COMPATIBILITY_DATE,
    ua_appname=ReactionsConfig.name,
    ua_version=__version__,
    ua_url=__url__,
    operations=[
        "GetIndustrySystems",
        "GetUniverseStationsStationId",
        "GetCharactersCharacterIdStandings",
        "GetCharactersCharacterIdSkills",
    ],
)


def get_industry_systems():
    return esi.industry_systems()


def get_system_information(station_id):
    return esi.station_information(station_id)


def get_character_standings(character_id):
    return esi.character_standings(character_id)


def get_character_skills(character_id):
    return esi.character_skills(character_id)


def default_reaction_structure_type_id(facility_size: str) -> Optional[int]:
    return DEFAULT_REACTION_STRUCTURE_TYPE_IDS.get(str(facility_size or "").lower())


def parse_reaction_rig_ids(raw_value: str) -> List[int]:
    rig_ids = []
    seen = set()

    for chunk in str(raw_value or "").replace("\n", ",").split(","):
        value = chunk.strip()
        if not value:
            continue

        try:
            rig_id = int(value)
        except (TypeError, ValueError):
            continue

        if rig_id <= 0 or rig_id in seen:
            continue

        seen.add(rig_id)
        rig_ids.append(rig_id)

    return rig_ids


def _decimal_or_none(value) -> Optional[Decimal]:
    if value in (None, ""):
        return None

    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _fraction_string(percent_value) -> Optional[str]:
    decimal_value = _decimal_or_none(percent_value)
    if decimal_value is None:
        return None

    fraction = decimal_value / Decimal("100")
    return format(fraction.normalize(), "f")


def build_reaction_cost_params(
    product_id: int,
    blueprint_id: int,
    runs: int,
    reactions_level: int,
    facility_tax_pct,
    reaction_cost_pct,
    facility_size: str,
    facility_location: str,
    solar_system_id: Optional[int] = None,
    structure_type_id: Optional[int] = None,
    rig_ids: Optional[List[int]] = None,
    advanced_industry_level: Optional[int] = None,
    system_cost_bonus_pct=None,
    alpha_clone: bool = False,
    material_prices: str = "",
) -> List[Tuple[str, str]]:
    params = [
        ("product_id", str(int(product_id))),
        ("blueprint_id", str(int(blueprint_id))),
        ("runs", str(int(runs))),
        ("reactions", str(int(reactions_level))),
    ]

    if solar_system_id:
        params.append(("system_id", str(int(solar_system_id))))

    security = SECURITY_CLASS_BY_LOCATION.get(str(facility_location or "").lower())
    if security and not solar_system_id:
        params.append(("security", security))

    structure_value = structure_type_id or default_reaction_structure_type_id(facility_size)
    if structure_value:
        params.append(("structure_type_id", str(int(structure_value))))

    for rig_id in rig_ids or []:
        params.append(("rig_id", str(int(rig_id))))

    facility_tax = _fraction_string(facility_tax_pct)
    if facility_tax is not None:
        params.append(("facility_tax", facility_tax))

    reaction_cost = _fraction_string(reaction_cost_pct)
    if reaction_cost is not None:
        params.append(("reaction_cost", reaction_cost))

    if advanced_industry_level is not None:
        params.append(("advanced_industry", str(int(advanced_industry_level))))

    system_cost_bonus = _fraction_string(system_cost_bonus_pct)
    if system_cost_bonus is not None:
        params.append(("system_cost_bonus", system_cost_bonus))

    if alpha_clone:
        params.append(("alpha", "true"))

    if material_prices:
        params.append(("material_prices", str(material_prices).strip()))

    return params


def get_reaction_cost(
    product_id: int,
    blueprint_id: int,
    runs: int,
    reactions_level: int,
    facility_tax_pct,
    reaction_cost_pct,
    facility_size: str,
    facility_location: str,
    solar_system_id: Optional[int] = None,
    structure_type_id: Optional[int] = None,
    rig_ids: Optional[List[int]] = None,
    advanced_industry_level: Optional[int] = None,
    system_cost_bonus_pct=None,
    alpha_clone: bool = False,
    material_prices: str = "",
) -> Optional[Dict[str, object]]:
    params = build_reaction_cost_params(
        product_id=product_id,
        blueprint_id=blueprint_id,
        runs=runs,
        reactions_level=reactions_level,
        facility_tax_pct=facility_tax_pct,
        reaction_cost_pct=reaction_cost_pct,
        facility_size=facility_size,
        facility_location=facility_location,
        solar_system_id=solar_system_id,
        structure_type_id=structure_type_id,
        rig_ids=rig_ids,
        advanced_industry_level=advanced_industry_level,
        system_cost_bonus_pct=system_cost_bonus_pct,
        alpha_clone=alpha_clone,
        material_prices=material_prices,
    )

    try:
        response = requests.get(
            "{0}/industry/cost".format(app_settings.AAREACTIONS_EVEREF_API_URL.rstrip("/")),
            params=params,
            timeout=app_settings.AAREACTIONS_EVEREF_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        logger.warning("EVE Ref reaction cost request failed for blueprint %s: %s", blueprint_id, exc)
        return None
    except ValueError as exc:
        logger.warning("EVE Ref reaction cost request returned invalid JSON for blueprint %s: %s", blueprint_id, exc)
        return None

    reaction_payload = payload.get("reaction", {})
    if not isinstance(reaction_payload, dict):
        logger.warning("EVE Ref reaction cost payload missing reaction node for blueprint %s.", blueprint_id)
        return None

    cost_payload = reaction_payload.get(str(product_id)) or reaction_payload.get(product_id)
    if cost_payload is None and len(reaction_payload) == 1:
        cost_payload = next(iter(reaction_payload.values()))

    if not isinstance(cost_payload, dict):
        logger.warning("EVE Ref reaction cost payload missing product %s for blueprint %s.", product_id, blueprint_id)
        return None

    total_job_cost = _decimal_or_none(cost_payload.get("total_job_cost"))
    if total_job_cost is None:
        logger.warning("EVE Ref reaction cost payload missing total_job_cost for blueprint %s.", blueprint_id)
        return None

    return {
        "total_job_cost": total_job_cost,
        "total_material_cost": _decimal_or_none(cost_payload.get("total_material_cost")),
        "time": cost_payload.get("time"),
        "query_params": params,
    }
