from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from eve_sde.models import ItemType

from aareactions.models import Reaction, ReactionSettings
from aareactions.views import InputView


class InputViewStepDisplayTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = get_user_model().objects.create_user(
            username="tester",
            email="tester@example.com",
            password="password",
        )
        ReactionSettings.objects.create(
            name="Default",
            refine_rate=Decimal("80.00"),
            input_price_basis="buy",
            output_price_basis="sell",
            broker_fee_pct=Decimal("3.00"),
            accounting_level=5,
            reaction_skill_level=5,
            facility_size="medium",
            facility_location="low",
            rig_me="none",
            rig_te="none",
            facility_tax_pct=Decimal("1.50"),
            cost_index_pct=Decimal("0.150"),
            scrap_metal_processing_level=0,
        )
        Reaction.objects.create(
            blueprint_type_id=9001,
            name="Test Reaction",
            time_seconds=60,
        )
        ItemType.objects.bulk_create(
            [
                ItemType(id=1, name="Input A", portion_size=1, volume=1.0, published=True),
                ItemType(id=2, name="Input B", portion_size=1, volume=1.0, published=True),
                ItemType(id=3, name="Output P", portion_size=1, volume=1.0, published=True),
            ]
        )

    def _post_data(self):
        return {
            "lines": "",
            "refine_rate": "80.00",
            "scrap_metal_processing_level": "0",
            "input_price_basis": "buy",
            "output_price_basis": "sell",
            "broker_fee_pct": "3.00",
            "accounting_level": "5",
            "reaction_skill_level": "5",
            "facility_size": "medium",
            "facility_location": "low",
            "rig_me": "none",
            "rig_te": "none",
            "facility_tax_pct": "1.50",
            "cost_index_pct": "0.150",
            "solar_system_id": "",
        }

    def test_step_display_uses_actual_runs_for_inputs_and_outputs(self):
        captured = {}
        stock = {1: 10, 2: 100}
        plans = [
            {
                "name": "Test Reaction",
                "blueprint_type_id": 9001,
                "time_seconds": 60,
                "per_run_requirements": {1: 10, 2: 1},
                "per_run_products": {3: 5},
                "have_any": True,
            }
        ]

        def fake_render(_request, _template_name, context):
            captured["context"] = context
            return HttpResponse("ok")

        def price_in(tid, _basis):
            return {1: Decimal("10.00"), 2: Decimal("1.00")}.get(int(tid), Decimal("0"))

        def price_out(tid, _basis):
            return {3: Decimal("100.00")}.get(int(tid), Decimal("0"))

        request = self.factory.post("/aareactions/", data=self._post_data())
        request.user = self.user

        with patch("aareactions.views.render", side_effect=fake_render), patch(
            "aareactions.views.parse_input_lines", return_value=[]
        ), patch(
            "aareactions.views.resolve_types", return_value=[]
        ), patch(
            "aareactions.views.categorize_items", return_value=[]
        ), patch(
            "aareactions.views.filter_by_settings", return_value=[]
        ), patch(
            "aareactions.views.build_initial_stock", return_value=(stock, [])
        ), patch(
            "aareactions.views.plan_reactions_with_chain", return_value=plans
        ), patch(
            "aareactions.views.price_input", side_effect=price_in
        ), patch(
            "aareactions.views.price_output", side_effect=price_out
        ):
            response = InputView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        chain = captured["context"]["chain_groups"][0][1][0]
        step = chain["steps"][0]

        self.assertEqual(step["runs"], 1)
        self.assertEqual(step["produced_qty"], 5)
        self.assertEqual(step["product_stats"]["value"], "500.00")

        inputs_by_name = {row["name"]: row for row in step["inputs"]}
        self.assertEqual(inputs_by_name["Input A"]["have"], 10)
        self.assertEqual(inputs_by_name["Input A"]["need_missing"], 0)
        self.assertEqual(inputs_by_name["Input B"]["have"], 1)
        self.assertEqual(inputs_by_name["Input B"]["need_missing"], 0)
