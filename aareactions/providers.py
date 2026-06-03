# Third Party
from allianceauth.services.hooks import get_extension_logger
from esi.models import Token
from esi.openapi_clients import ESIClientProvider

# aareactions
from aareactions import __url__, __version__, app_settings
from aareactions.apps import ReactionsConfig


logger = get_extension_logger(__name__)


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
