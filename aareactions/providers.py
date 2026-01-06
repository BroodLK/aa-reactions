from esi.openapi_clients import ESIClientProvider
from esi.helpers import get_token

from . import __version__, __url__

from .apps import ReactionsConfig
from .models import CharacterToken

esi = ESIClientProvider(
    compatibility_date="2025-09-30",
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
    return esi.client.Industry.GetIndustrySystems().results()

def get_system_information(station_id: int):
    return esi.client.Universe.GetUniverseStationsStationId(station_id=station_id).results()

def get_character_standings(character_id: int):
    req_scopes = ['esi-characters.read_standings.v1']
    return esi.client.Character.GetCharactersCharacterIdStandings(character_id=character_id, token=get_token(character_id, req_scopes)).results()

def get_character_skills(character_id: int):
    req_scopes = ['esi-skills.read_skills.v1']
    return esi.client.Skills.GetCharactersCharacterIdSkills(character_id=character_id, token=get_token(character_id, req_scopes)).results()

skills = [
    45746,  # Reactions
    16622,  # Accounting
    3446,   # Broker Relations
    3385,   # Reprocessing
    3389,   # Reprocessing Efficiency
    46152,  # Ubiquitous Moon Ore Processing
    46153,  # Common Moon Ore Processing
    46156,	# Exceptional Moon Ore Processing
    46155,	# Rare Moon Ore Processing
    46154,	# Uncommon Moon Ore Processing
    12196,	# Scrapmetal Processing
]
