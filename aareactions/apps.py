"""App Configuration"""

# Django
from django.apps import AppConfig

from aareactions import __version__


class ReactionsConfig(AppConfig):
    """App Config"""

    name = "aareactions"
    label = "aareactions"
    verbose_name = f"Reactions v{__version__}"
