# Django
from django.urls import path

from .apps import ReactionsConfig
from .views import InputView, add_character_token, solar_system_reaction_index, solar_system_search

app_name = ReactionsConfig.name

urlpatterns = [
    path("", InputView.as_view(), name="index"),
    path("systems/search/", solar_system_search, name="solar-system-search"),
    path("systems/reaction-index/", solar_system_reaction_index, name="solar-system-reaction-index"),
    path("character/add/", add_character_token, name="add_character"),
]
