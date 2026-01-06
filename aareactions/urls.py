from django.urls import path
from .apps import ReactionsConfig
from .views import InputView, solar_system_search, add_character_token


app_name = ReactionsConfig.name

urlpatterns = [
    path("", InputView.as_view(), name="index"),
    path("systems/search/", solar_system_search, name="solar-system-search"),
    path("character/add/", add_character_token, name="add_character")
]
