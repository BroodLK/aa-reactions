from decimal import Decimal
from typing import ClassVar

from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone

from eveuniverse.models import EveType
from allianceauth.eveonline.models import EveCharacter
from esi.models import Token

class General(models.Model):
    class Meta:
        managed = False
        default_permissions = ()
        permissions = (
            ("basic_access", "Can access reactions app"),
            ("reactions_admin", "Can manage default reaction setting")
        )

class ContactTokenQueryset(models.QuerySet):
    def with_valid_tokens(self):
        valid_tokens = Token.objects.all().require_valid()
        return self.filter(token__in=valid_tokens)


class ReactionTokenManager(models.Manager):
    def get_queryset(self):
        return ContactTokenQueryset(self.model, using=self._db)

    def with_valid_tokens(self):
        return self.get_queryset().with_valid_tokens()


class ReactionToken(models.Model):
    token = models.ForeignKey(Token, on_delete=models.CASCADE, related_name='+')
    last_update = models.DateTimeField(default=timezone.now)
    objects: ClassVar[ReactionTokenManager] = ReactionTokenManager()

    class Meta:
        abstract = True
        default_permissions = ()


class CharacterToken(ReactionToken):
    character = models.OneToOneField(EveCharacter, on_delete=models.CASCADE, related_name='+')

    class Meta:
        default_permissions = ()

    def __str__(self) -> str:
        return f"{self.character.character_name} ({self.character.character_id})"

    @classmethod
    def visible_for(cls, user):
        if user.is_superuser:
            return cls.objects.all()

class CharacterReactions(models.Model):
    character = models.ForeignKey(CharacterToken, on_delete=models.CASCADE, related_name='+')
    reaction_skill_level = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(0), MaxValueValidator(5)])
    broker_relations_skill_level = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(0), MaxValueValidator(5)])
    scrap_metal_processing_level = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(0), MaxValueValidator(5)])
    accounting_level = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(0), MaxValueValidator(5)])
    reprocessing_level = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(0), MaxValueValidator(5)])
    reprocessing_efficiency = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(0), MaxValueValidator(5)])
    ubiquitous_moon_processing_level = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(0), MaxValueValidator(5)])
    common_moon_processing_level = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(0), MaxValueValidator(5)])
    uncommon_moon_processing_level = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(0), MaxValueValidator(5)])
    rare_moon_processing_level = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(0), MaxValueValidator(5)])
    exceptional_moon_processing_level = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(0), MaxValueValidator(5)])
    last_update = models.DateTimeField(default=timezone.now)

class CharacterStandings(models.Model):
    character = models.ForeignKey(CharacterToken, on_delete=models.CASCADE, related_name='+')
    standing = models.PositiveIntegerField(default=0)
    entity_id = models.BigIntegerField(default=0)
    entity_type = models.CharField(max_length=100, default="")
    last_update = models.DateTimeField(default=timezone.now)

class SystemIndices(models.Model):
    solar_system_id = models.IntegerField(db_index=True, unique=True)
    activity = models.CharField(max_length=100)
    cost_index = models.DecimalField(max_digits=6, decimal_places=3)
    last_update = models.DateTimeField(default=timezone.now)

class ReactionSettings(models.Model):
    name = models.CharField(max_length=100, default="Default")
    allowed_group_ids = models.JSONField(default=list)
    refine_rate = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("80.00"))
    input_price_basis = models.CharField(max_length=8, choices=(("buy", "Buy"), ("sell", "Sell")), default="buy")
    output_price_basis = models.CharField(max_length=8, choices=(("buy", "Buy"), ("sell", "Sell")), default="sell")
    broker_fee_pct = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("3.00"), validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))])
    accounting_level = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(0), MaxValueValidator(5)])
    reaction_skill_level = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(0), MaxValueValidator(5)])
    facility_size = models.CharField(max_length=8, choices=(("medium", "Medium"), ("large", "Large")), default="medium")
    facility_location = models.CharField(max_length=8, choices=(("low", "Low"), ("null", "Null"), ("wh", "WH")), default="low")
    rig_me = models.CharField(max_length=8, choices=(("none", "None"), ("t1", "T1 ME"), ("t2", "T2 ME")), default="none")
    rig_te = models.CharField(max_length=8, choices=(("none", "None"), ("t1", "T1 TE"), ("t2", "T2 TE")), default="none")
    repro_rig_me = models.CharField(max_length=8, choices=(("none", "None"), ("t1", "T1"), ("t2", "T2")), default="none")
    facility_tax_pct = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("1.50"), validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))])
    cost_index_pct = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal("0.150"), validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))])
    scrap_metal_processing_level = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(0), MaxValueValidator(5)])
    refine_implant = models.PositiveSmallIntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(4)])

    buyback_enabled = models.BooleanField(default=False)
    buyback_pct = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("90.00"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    buyback_basis = models.CharField(
        max_length=8, choices=(("buy", "Buy"), ("sell", "Sell")), default="buy"
    )

    verbose_name = "Reaction Settings"
    verbose_name_plural = "Reaction Settings"

    def __str__(self) -> str:
        return self.name


class Reaction(models.Model):
    blueprint_type_id = models.IntegerField(db_index=True, unique=True)
    name = models.CharField(max_length=200, blank=True, default="")
    time_seconds = models.IntegerField(default=0, validators=[MinValueValidator(0)])

    def __str__(self) -> str:
        return self.name or f"Reaction {self.blueprint_type_id}"


class ReactionMaterial(models.Model):
    reaction = models.ForeignKey(Reaction, related_name="materials", on_delete=models.CASCADE)
    type = models.ForeignKey(EveType, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        unique_together = (("reaction", "type"),)


class ReactionProduct(models.Model):
    reaction = models.ForeignKey(Reaction, related_name="products", on_delete=models.CASCADE)
    type = models.ForeignKey(EveType, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        unique_together = (("reaction", "type"),)


class EveTypePrice(models.Model):
    eve_type = models.OneToOneField(EveType, on_delete=models.CASCADE, related_name="aareactions_price")
    buy = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0"))
    sell = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0"))
    buy_average = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0"))
    sell_average = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0"))
    updated = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.eve_type_id}"
