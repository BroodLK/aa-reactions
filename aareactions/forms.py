# file: aareactions/forms.py
from django import forms

INPUT_BASIS_CHOICES = (("buy", "Buy"), ("sell", "Sell"))
OUTPUT_BASIS_CHOICES = (("buy", "Buy"), ("sell", "Sell"))
FACILITY_SIZE_CHOICES = (("medium", "Medium"), ("large", "Large"))
FACILITY_LOCATION_CHOICES = (("low", "Low"), ("null", "Null"), ("wh", "WH"))
RIG_ME_CHOICES = (("none", "None"), ("t1", "T1 ME"), ("t2", "T2 ME"))
RIG_TE_CHOICES = (("none", "None"), ("t1", "T1 TE"), ("t2", "T2 TE"))

class InputForm(forms.Form):
    lines = forms.CharField(
        label="Paste items",
        help_text="One per line as: <type_id>, <quantity> (e.g. 34, 250000)",
        widget=forms.Textarea(attrs={"rows": 6, "class": "form-control"}),
        required=False,
    )
    refine_rate = forms.DecimalField(
        label="Refine rate (%)",
        min_value=0,
        max_value=100,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        required=True,
    )
    scrap_metal_processing_level = forms.IntegerField(
        label="Scrap metal processing",
        min_value=0,
        max_value=5,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
        required=True,
    )
    input_price_basis = forms.ChoiceField(
        label="Input method",
        choices=INPUT_BASIS_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
        required=True,
    )
    output_price_basis = forms.ChoiceField(
        label="Output method",
        choices=OUTPUT_BASIS_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
        required=True,
    )
    broker_fee_pct = forms.DecimalField(
        label="Broker fee (%)",
        min_value=0,
        max_value=100,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        required=True,
    )
    accounting_level = forms.IntegerField(
        label="Accounting level",
        min_value=0,
        max_value=5,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
        required=True,
    )
    reaction_skill_level = forms.IntegerField(
        label="Reaction skill",
        min_value=0,
        max_value=5,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
        required=True,
    )
    number_of_slots = forms.IntegerField(
        label="Number of slots",
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
        required=True,
        initial=1,
    )
    facility_size = forms.ChoiceField(
        label="Facility size",
        choices=FACILITY_SIZE_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
        required=True,
    )
    facility_location = forms.ChoiceField(
        label="Facility location",
        choices=FACILITY_LOCATION_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
        required=True,
    )
    rig_me = forms.ChoiceField(
        label="ME rig",
        choices=RIG_ME_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
        required=True,
    )
    rig_te = forms.ChoiceField(
        label="TE rig",
        choices=RIG_TE_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
        required=True,
    )
    facility_tax_pct = forms.DecimalField(
        label="Facility tax (%)",
        min_value=0,
        max_value=100,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        required=True,
    )
    cost_index_pct = forms.DecimalField(
        label="Cost index (%)",
        min_value=0,
        max_value=100,
        decimal_places=3,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.001"}),
        required=True,
    )
    everef_structure_type_id = forms.IntegerField(
        label="EVE Ref structure type ID",
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
        required=False,
    )
    everef_rig_ids = forms.CharField(
        label="EVE Ref rig IDs",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Comma separated rig IDs",
            }
        ),
        required=False,
    )
    advanced_industry_level = forms.IntegerField(
        label="Advanced industry",
        min_value=0,
        max_value=5,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
        required=False,
        initial=5,
    )
    system_cost_bonus_pct = forms.DecimalField(
        label="System cost bonus (%)",
        min_value=-100,
        max_value=100,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        required=False,
        initial=0,
    )
    everef_material_prices = forms.CharField(
        label="Material prices source",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Optional EVE Ref material_prices value",
            }
        ),
        required=False,
    )
    alpha_clone = forms.BooleanField(
        label="Alpha clone",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    use_buyback_for_stock = forms.BooleanField(
        label="Use buyback for stock",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    solar_system_id = forms.IntegerField(
        required=False,
        widget=forms.HiddenInput()
    )
