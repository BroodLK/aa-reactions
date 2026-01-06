from django import forms
from django.contrib import admin
from .models import ReactionSettings, Reaction, ReactionMaterial, ReactionProduct, EveTypePrice, CharacterToken, CharacterReactions, CharacterStandings


class ReactionSettingsForm(forms.ModelForm):
    class Meta:
        model = ReactionSettings
        fields = (
            "name",
            "refine_rate",
            "input_price_basis",
            "output_price_basis",
            "broker_fee_pct",
            "accounting_level",
            "reaction_skill_level",
            "facility_size",
            "facility_location",
            "rig_me",
            "rig_te",
            "facility_tax_pct",
            "cost_index_pct",
            "scrap_metal_processing_level",
            "buyback_enabled",
            "buyback_pct",
            "buyback_basis",
        )


class ReactionMaterialInline(admin.TabularInline):
    model = ReactionMaterial
    extra = 0


class ReactionProductInline(admin.TabularInline):
    model = ReactionProduct
    extra = 0


@admin.register(ReactionSettings)
class ReactionSettingsAdmin(admin.ModelAdmin):
    verbose_name_plural = "Reaction Settings"
    form = ReactionSettingsForm
    list_display = (
        "name",
        "refine_rate",
        "input_price_basis",
        "output_price_basis",
        "broker_fee_pct",
        "accounting_level",
        "reaction_skill_level",
        "facility_size",
        "facility_location",
        "rig_me",
        "rig_te",
        "facility_tax_pct",
        "cost_index_pct",
        "buyback_enabled",
        "buyback_pct",
        "buyback_basis",
    )
    fieldsets = (
        (None, {"fields": ("name",)}),
        ("General", {"fields": ("reaction_skill_level",)}),
        ("Refining", {"fields": ("refine_rate", "scrap_metal_processing_level")}),
        ("Pricing", {"fields": ("input_price_basis", "output_price_basis", "broker_fee_pct", "accounting_level")}),
        ("Facility", {"fields": ("facility_size", "facility_location", "rig_me", "rig_te")}),
        ("Taxes", {"fields": ("facility_tax_pct", "cost_index_pct")}),
        ("Buyback", {"fields": ("buyback_enabled", "buyback_pct", "buyback_basis")}),
    )

    def has_module_permission(self, request):
        return request.user.has_perm(f"{self.model._meta.app_label}.reactions_admin")

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm(f"{self.model._meta.app_label}.reactions_admin")

    def has_add_permission(self, request):
        return request.user.has_perm(f"{self.model._meta.app_label}.reactions_admin")

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm(f"{self.model._meta.app_label}.reactions_admin")

    def has_delete_permission(self, request, obj=None):
        return request.user.has_perm(f"{self.model._meta.app_label}.reactions_admin")


@admin.register(Reaction)
class ReactionAdmin(admin.ModelAdmin):
    list_display = ("name", "blueprint_type_id", "time_seconds")
    search_fields = ("name", "blueprint_type_id")
    inlines = [ReactionMaterialInline, ReactionProductInline]


@admin.register(EveTypePrice)
class EveTypePriceAdmin(admin.ModelAdmin):
    list_display = ("eve_type", "buy", "sell", "buy_average", "sell_average", "updated")
    search_fields = ("eve_type__name", "eve_type__id")

@admin.register(CharacterReactions)
class CharacterReactionsAdmin(admin.ModelAdmin):
    list_display = (
        "character",
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
    )
    list_filter = (
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
    )
    search_fields = ("character__character__character_name", "character__character__character_id")

@admin.register(CharacterStandings)
class CharacterStandingsAdmin(admin.ModelAdmin):
    list_display = ("character", "entity_id", "entity_type", "standing", "last_update")
    list_filter = ("entity_type",)
    search_fields = ("character__character__character_name", "character__character__character_id", "entity_id")
