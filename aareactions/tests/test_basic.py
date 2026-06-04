from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from eve_sde.models import ItemType

from aareactions.helper import effective_time_seconds, te_bonus_pct
from aareactions.models import Reaction, ReactionSettings, SystemIndices, UserReactionSettings
from aareactions.providers import build_reaction_cost_params, default_reaction_structure_type_id, parse_reaction_rig_ids
from aareactions.views import InputView, solar_system_reaction_index, split_runs_across_slots


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
            "number_of_slots": "1",
            "facility_size": "medium",
            "facility_location": "low",
            "rig_me": "none",
            "rig_te": "none",
            "facility_tax_pct": "1.50",
            "cost_index_pct": "0.150",
            "everef_structure_type_id": "35835",
            "everef_rig_ids": "123,456",
            "advanced_industry_level": "5",
            "system_cost_bonus_pct": "-0.50",
            "everef_material_prices": "sell",
            "alpha_clone": "on",
            "use_buyback_for_stock": "on",
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
        ), patch(
            "aareactions.views.get_reaction_cost", return_value=None
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

    def test_step_fees_use_everef_total_job_cost_when_available(self):
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
            "aareactions.views.price_input", return_value=Decimal("10.00")
        ), patch(
            "aareactions.views.price_output", return_value=Decimal("100.00")
        ), patch(
            "aareactions.views.get_reaction_cost",
            return_value={"total_job_cost": Decimal("42.00"), "query_params": []},
        ):
            response = InputView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        chain = captured["context"]["chain_groups"][0][1][0]
        step = chain["steps"][0]
        self.assertEqual(step["fees_display"], "42.00")
        self.assertEqual(step["fee_source"], "EVE Ref")

    def test_get_prefills_saved_user_defaults(self):
        captured = {}
        UserReactionSettings.objects.create(
            user=self.user,
            refine_rate=Decimal("87.50"),
            input_price_basis="sell",
            output_price_basis="buy",
            broker_fee_pct=Decimal("2.25"),
            accounting_level=4,
            reaction_skill_level=3,
            number_of_slots=7,
            facility_size="large",
            facility_location="null",
            rig_me="t2",
            rig_te="t1",
            facility_tax_pct=Decimal("2.00"),
            cost_index_pct=Decimal("0.321"),
            scrap_metal_processing_level=2,
            solar_system_id=30000142,
            everef_structure_type_id=35836,
            everef_rig_ids="37180,37183",
            advanced_industry_level=4,
            system_cost_bonus_pct=Decimal("-0.50"),
            everef_material_prices="sell",
            alpha_clone=True,
            use_buyback_for_stock=True,
        )

        def fake_render(_request, _template_name, context):
            captured["context"] = context
            return HttpResponse("ok")

        request = self.factory.get("/aareactions/")
        request.user = self.user

        with patch("aareactions.views.render", side_effect=fake_render), patch(
            "aareactions.views.EveSolarSystem.objects.only"
        ) as mock_only:
            mock_only.return_value.get.return_value.name = "Jita"
            response = InputView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        form = captured["context"]["form"]
        self.assertEqual(form["refine_rate"].value(), Decimal("87.50"))
        self.assertEqual(form["facility_size"].value(), "large")
        self.assertEqual(form["number_of_slots"].value(), 7)
        self.assertEqual(form["everef_structure_type_id"].value(), 35836)
        self.assertEqual(form["use_buyback_for_stock"].value(), True)
        self.assertEqual(captured["context"]["selected_system_name"], "Jita")

    def test_post_saves_user_defaults(self):
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
            "aareactions.views.price_input", return_value=Decimal("10.00")
        ), patch(
            "aareactions.views.price_output", return_value=Decimal("100.00")
        ), patch(
            "aareactions.views.get_reaction_cost", return_value=None
        ):
            response = InputView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        user_settings = UserReactionSettings.objects.get(user=self.user)
        self.assertEqual(user_settings.refine_rate, Decimal("80.00"))
        self.assertEqual(user_settings.facility_size, "medium")
        self.assertEqual(user_settings.number_of_slots, 1)
        self.assertEqual(user_settings.everef_structure_type_id, 35835)
        self.assertEqual(user_settings.everef_rig_ids, "123,456")
        self.assertEqual(user_settings.use_buyback_for_stock, True)
        self.assertEqual(user_settings.everef_material_prices, "sell")

    def test_step_time_uses_slots_per_step_distribution(self):
        captured = {}
        stock = {1: 510, 2: 51}
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
        post_data = self._post_data()
        post_data["number_of_slots"] = "50"

        def fake_render(_request, _template_name, context):
            captured["context"] = context
            return HttpResponse("ok")

        request = self.factory.post("/aareactions/", data=post_data)
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
            "aareactions.views.price_input", return_value=Decimal("10.00")
        ), patch(
            "aareactions.views.price_output", return_value=Decimal("100.00")
        ), patch(
            "aareactions.views.get_reaction_cost", return_value=None
        ):
            response = InputView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        chain = captured["context"]["chain_groups"][0][1][0]
        step = chain["steps"][0]
        runs_per_slot = split_runs_across_slots(step["runs"], step["number_of_slots"])
        self.assertEqual(step["runs"], 51)
        self.assertEqual(step["number_of_slots"], 50)
        self.assertEqual(len(runs_per_slot), 50)
        self.assertEqual(sum(runs_per_slot), 51)
        self.assertEqual(runs_per_slot.count(2), 1)
        self.assertEqual(runs_per_slot.count(1), 49)
        self.assertEqual(step["time_batches"], max(runs_per_slot))
        self.assertEqual(step["runs_per_slot_total"], sum(runs_per_slot))
        expected_per_run_time = int(effective_time_seconds(60, 5, "medium", te_bonus_pct("none", "low")))
        self.assertEqual(step["time_total_seconds"], expected_per_run_time * max(runs_per_slot))
        self.assertEqual(chain["total_time_seconds"], expected_per_run_time * max(runs_per_slot))


class EveRefProviderTests(TestCase):
    def test_split_runs_across_slots_preserves_total_runs(self):
        runs_per_slot = split_runs_across_slots(1298, 50)

        self.assertEqual(len(runs_per_slot), 50)
        self.assertEqual(sum(runs_per_slot), 1298)
        self.assertEqual(runs_per_slot.count(26), 48)
        self.assertEqual(runs_per_slot.count(25), 2)
        self.assertEqual(max(runs_per_slot), 26)

    def test_build_reaction_cost_params_uses_form_inputs(self):
        params = build_reaction_cost_params(
            product_id=3,
            blueprint_id=9001,
            runs=4,
            reactions_level=5,
            facility_tax_pct=Decimal("1.50"),
            reaction_cost_pct=Decimal("0.150"),
            facility_size="medium",
            facility_location="low",
            solar_system_id=30000142,
            structure_type_id=None,
            rig_ids=parse_reaction_rig_ids("37180, 37183"),
            advanced_industry_level=4,
            system_cost_bonus_pct=Decimal("-0.50"),
            alpha_clone=True,
            material_prices="sell",
        )

        self.assertIn(("product_id", "3"), params)
        self.assertIn(("blueprint_id", "9001"), params)
        self.assertIn(("runs", "4"), params)
        self.assertIn(("reactions", "5"), params)
        self.assertIn(("system_id", "30000142"), params)
        self.assertIn(("structure_type_id", str(default_reaction_structure_type_id("medium"))), params)
        self.assertIn(("rig_id", "37180"), params)
        self.assertIn(("rig_id", "37183"), params)
        self.assertIn(("facility_tax", "0.015"), params)
        self.assertIn(("reaction_cost", "0.0015"), params)
        self.assertIn(("advanced_industry", "4"), params)
        self.assertIn(("system_cost_bonus", "-0.005"), params)
        self.assertIn(("alpha", "true"), params)
        self.assertIn(("material_prices", "sell"), params)

    def test_parse_reaction_rig_ids_filters_invalid_values(self):
        self.assertEqual(parse_reaction_rig_ids("37180, bad, 37180,\n37183"), [37180, 37183])


class SolarSystemReactionIndexTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = get_user_model().objects.create_user(
            username="indexer",
            email="indexer@example.com",
            password="password",
        )

    def test_endpoint_returns_cached_reaction_index(self):
        SystemIndices.objects.create(
            solar_system_id=30000142,
            activity="reactions",
            cost_index=Decimal("0.321"),
        )

        request = self.factory.get("/aareactions/systems/reaction-index/?solar_system_id=30000142")
        request.user = self.user

        with patch("aareactions.views.EveSolarSystem.objects.select_related") as mock_select:
            mock_select.return_value.get.return_value.name = "Jita"
            response = solar_system_reaction_index(request)

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {
                "system_name": "Jita",
                "cost_index_pct": "0.321",
                "cost_index_display": "0.321%",
                "source": "cache",
                "error": None,
            },
        )
