from decimal import Decimal
from typing import Dict, List

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.db import IntegrityError, transaction
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.utils.translation import gettext
from django.views import View
from django.http import JsonResponse

from allianceauth.eveonline.models import EveCharacter

from esi.models import Token
from esi.decorators import token_required

from .forms import InputForm
from .models import ReactionSettings, SystemIndices, CharacterToken
from .tasks import update_character_skills
from .tasks import update_character_standings

from .helper import (
    filter_by_settings,
    parse_input_lines,
    resolve_types,
    categorize_items,
    build_initial_stock,
    plan_reactions_with_chain,
    sales_tax_pct,
    me_bonus_pct,
    te_bonus_pct,
    effective_time_seconds,
    apply_me_to_requirements,
    fmt_duration,
    is_fuel_id,
    refined_partner_type_id,
    has_refined_already,
    runcap_with_present,
    runcap_with_supply,
    price_input,
    price_output,
    add_supply,
    find_feeders_for_parent,
    reprocess_unrefined_in_stock,
    build_reprocess_step,
    consumes_any_of,
    produces_unrefined,
    self_recovery_loss,
    dec_from,
)
from .pricing import resolve_price_value
from .providers import get_industry_systems

from eveuniverse.models import EveSolarSystem
from eveuniverse.models import EveType

@login_required
@token_required(scopes=['esi-characters.read_standings.v1', 'esi-skills.read_skills.v1'])
def add_character_token(request, token: Token):

    if CharacterToken.objects.filter(character_id=token.character_id).exists():
        messages.error(request, gettext('Character reaction skills already being tracked.'))
        return redirect('aa_contacts:index')

    eve_char, _ = EveCharacter.objects.get_or_create(
        character_id=token.character_id,
        defaults={"character_name": getattr(token, "character_name", str(token.character_id))}
    )

    try:
        with transaction.atomic():
            ct, created = CharacterToken.objects.get_or_create(
                character=eve_char,
                defaults={"token": token}
            )
            if not created:
                if ct.token_id != token.id:
                    ct.token = token
                    ct.save(update_fields=["token", "last_update"])
    except IntegrityError:
        messages.info(request, gettext("Character reaction skills already being tracked."))
        return redirect('aareactions:index')


    update_character_skills.delay(character_id=token.character_id)
    update_character_standings.delay(character_id=token.character_id)

    messages.success(request, gettext('Reaction skills and standings are now being tracked.'))
    return redirect('aareactions:index')

@login_required
def solar_system_search(request):
    q = (request.GET.get("q") or "").strip()
    if not q:
        return JsonResponse([], safe=False)
    qs = (
        EveSolarSystem.objects.filter(name__icontains=q)
        .only("id", "name")
        .order_by("name")[:20]
    )
    data = [{"id": s.id, "text": s.name} for s in qs]
    return JsonResponse(data, safe=False)

@method_decorator(login_required, name="dispatch")
class InputView(View):
    template_name = "aareactions/input.html"

    def get(self, request):
        settings = ReactionSettings.objects.order_by("id").first()
        initial = {}
        if settings:
            initial = {
                "refine_rate": settings.refine_rate,
                "input_price_basis": settings.input_price_basis,
                "output_price_basis": settings.output_price_basis,
                "broker_fee_pct": settings.broker_fee_pct,
                "accounting_level": settings.accounting_level,
                "reaction_skill_level": settings.reaction_skill_level,
                "facility_size": settings.facility_size,
                "facility_location": settings.facility_location,
                "rig_me": settings.rig_me,
                "rig_te": settings.rig_te,
                "facility_tax_pct": settings.facility_tax_pct,
                "cost_index_pct": settings.cost_index_pct,
                "scrap_metal_processing_level": settings.scrap_metal_processing_level,
            }
        form = InputForm(initial=initial)
        return render(request, self.template_name, {"form": form, "settings": settings})

    def post(self, request):
        form = InputForm(request.POST)
        settings = ReactionSettings.objects.order_by("id").first()
        if not settings:
            messages.error(request, "Settings not configured.")
            return render(request, self.template_name, {"form": form, "settings": None})
        if not form.is_valid():
            return render(request, self.template_name, {"form": form, "settings": settings})

        refine_rate_pct = Decimal(form.cleaned_data.get("refine_rate") or settings.refine_rate)
        if refine_rate_pct <= 1:
            refine_rate_pct = refine_rate_pct * Decimal("100")
        refine_rate = refine_rate_pct / Decimal("100")

        smp_level = int(
            form.cleaned_data.get(
                "scrap_metal_processing_level", getattr(settings, "scrap_metal_processing_level", 0)
            )
            or 0
        )
        smp_rate_pct = (Decimal("50") * (Decimal("1.0") + Decimal(smp_level) * Decimal("0.02"))).quantize(
            Decimal("0.01")
        )
        if smp_rate_pct > Decimal("55"):
            smp_rate_pct = Decimal("55")
        unrefined_refine_rate = smp_rate_pct / Decimal("100")

        input_basis = form.cleaned_data.get("input_price_basis") or settings.input_price_basis
        output_basis = form.cleaned_data.get("output_price_basis") or settings.output_price_basis
        broker_fee_pct = Decimal(form.cleaned_data.get("broker_fee_pct") or settings.broker_fee_pct)
        accounting_level = int(form.cleaned_data.get("accounting_level") or settings.accounting_level)
        reaction_skill_level = int(form.cleaned_data.get("reaction_skill_level") or settings.reaction_skill_level)
        facility_size = form.cleaned_data.get("facility_size") or settings.facility_size
        facility_location = form.cleaned_data.get("facility_location") or settings.facility_location
        rig_me = form.cleaned_data.get("rig_me") or settings.rig_me
        rig_te = form.cleaned_data.get("rig_te") or settings.rig_te
        facility_tax_pct = Decimal(form.cleaned_data.get("facility_tax_pct") or settings.facility_tax_pct)
        cost_index_pct = Decimal(form.cleaned_data.get("cost_index_pct") or settings.cost_index_pct)

        selected_system_id = form.cleaned_data.get("solar_system_id")
        selected_system_name = None
        selected_reaction_index_pct = None
        if selected_system_id:
            try:
                sys = EveSolarSystem.objects.select_related("eve_constellation__eve_region").get(id=int(selected_system_id))
                selected_system_name = sys.name
            except EveSolarSystem.DoesNotExist:
                sys = None

            form_override = None
            try:
                form_ci = Decimal(form.cleaned_data.get("cost_index_pct") or "0")
                if form_ci > 0:
                    form_override = form_ci.quantize(Decimal("0.001"))
            except Exception:
                form_override = None


            si = SystemIndices.objects.filter(solar_system_id=int(selected_system_id), activity="reactions").first()
            cached_is_fresh = bool(si and (timezone.now() - si.last_update).total_seconds() <= 15 * 60)
            cached_value = Decimal(si.cost_index).quantize(Decimal("0.001")) if si else None

            if form_override is not None:
                selected_reaction_index_pct = form_override
                cost_index_pct = form_override
            elif cached_is_fresh:
                selected_reaction_index_pct = cached_value
                cost_index_pct = cached_value
            else:
                try:
                    data = get_industry_systems()
                except Exception:
                    data = []
                    messages.warning(
                        request,
                        "Could not contact ESI to fetch Industry cost indices."
                    )

                def _get(obj, key, default=None):
                    if isinstance(obj, dict):
                        return obj.get(key, default)
                    return getattr(obj, key, default)

                entry = next(
                    (
                        row for row in (data or [])
                        if int(_get(row, "solar_system_id", _get(row, "solarSystemID", -1))) == int(selected_system_id)
                    ),
                    None
                )

                idx_pct = None
                if entry:
                    try:
                        cost_indices = _get(entry, "cost_indices", _get(entry, "costIndices", [])) or []
                        idx = None
                        for ci in cost_indices:
                            activity = str(_get(ci, "activity", "") or "").lower()
                            if activity in {"reaction", "reactions"}:
                                idx = _get(ci, "cost_index", None)
                                break
                        if idx is not None:
                            idx_pct = (Decimal(str(idx)) * Decimal("100")).quantize(Decimal("0.001"))
                    except Exception:
                        idx_pct = None

                if idx_pct is not None:
                    selected_reaction_index_pct = idx_pct
                    cost_index_pct = idx_pct
                    now = timezone.now()
                    if not si:
                        SystemIndices.objects.create(
                            solar_system_id=int(selected_system_id),
                            activity="reactions",
                            cost_index=idx_pct,
                            last_update=now,
                        )
                    else:
                        if (now - si.last_update).total_seconds() > 15 * 60:
                            si.cost_index = idx_pct
                            si.last_update = now
                            si.save(update_fields=["cost_index", "last_update"])
                else:
                    # ESI failed or did not provide: fall back to stored model if exists; else keep current (settings/form default)
                    if cached_value is not None:
                        selected_reaction_index_pct = cached_value
                        cost_index_pct = cached_value
                    else:
                        # As a last resort, only use form if > 0; otherwise leave as settings default
                        if form_override is not None:
                            selected_reaction_index_pct = form_override
                            cost_index_pct = form_override
                        elif selected_system_name:
                            messages.info(
                                request,
                                f"No Industry (Reactions) cost index available for {selected_system_name}. Using default settings value."
                            )

        scc_pct = Decimal("4.00")

        use_buyback = bool(request.POST.get("use_buyback_for_stock"))
        buyback_pct = Decimal(getattr(settings, "buyback_pct", Decimal("90.00")))
        buyback_basis = getattr(settings, "buyback_basis", "buy")
        buyback_mult = (buyback_pct / Decimal("100")).quantize(Decimal("0.0001"))

        def _buyback_unit(tid: int) -> Decimal:
            base = price_input(int(tid), buyback_basis)
            return (base * buyback_mult).quantize(Decimal("0.0001"))

        lines = form.cleaned_data["lines"]
        parsed_pairs = parse_input_lines(lines)
        resolved = resolve_types(parsed_pairs)
        categorized = categorize_items(resolved)
        categorized = filter_by_settings(categorized, settings)

        direct_inputs_rows = []
        direct_inputs_total = Decimal("0")
        direct_inputs_total_m3 = Decimal("0")
        for p in categorized:
            if p.category != "material":
                continue
            et = p.evetype
            qty = int(p.quantity or 0)
            if qty <= 0:
                continue
            vol_unit = Decimal(getattr(et, "volume", 0) or 0)
            unit = resolve_price_value(int(et.id), input_basis) or Decimal("0")
            val = unit * Decimal(qty)
            m3 = vol_unit * Decimal(qty)
            direct_inputs_rows.append(
                {
                    "type_id": int(et.id),
                    "type_name": et.name,
                    "qty": qty,
                    "unit_price": f"{unit:,.2f}",
                    "value": f"{val:,.2f}",
                    "m3": f"{m3:,.2f}",
                }
            )
            direct_inputs_total += val
            direct_inputs_total_m3 += m3

        stock, refined_rows_src = build_initial_stock(categorized, refine_rate, unrefined_refine_rate)

        already = set(stock.keys())
        extra_ids = set()
        try:
            for pl in resolved:
                et = getattr(pl, "evetype", None)
                qty = int(getattr(pl, "quantity", 0) or 0)
                if not et or qty <= 0:
                    continue
                name_l = (et.name or "").lower()
                if "fuel block" in name_l:
                    pass
                if int(et.id) not in already:
                    stock[int(et.id)] = stock.get(int(et.id), 0) + qty
                    extra_ids.add(int(et.id))
        except Exception:
            pass

        type_ids = set(tid for tid, _ in refined_rows_src) | set(stock.keys()) | extra_ids
        plans_raw = plan_reactions_with_chain(stock)
        for p in plans_raw:
            type_ids.update((p.get("per_run_requirements") or {}).keys())
            type_ids.update((p.get("per_run_products") or {}).keys())
        type_map = {
            t.id: t
            for t in EveType.objects.filter(id__in=list(type_ids)).only("id", "name", "volume", "portion_size")
        }

        unrefinables = []
        unref_total_val = Decimal("0")
        for tid in extra_ids:
            et = type_map.get(tid)
            if not et:
                continue
            qty = stock.get(tid, 0)
            up = price_input(int(tid), input_basis)
            val = up * Decimal(qty)
            unrefinables.append(
                {
                    "type_id": tid,
                    "type_name": et.name,
                    "qty": qty,
                    "unit_price": f"{up:,.2f}",
                    "value": f"{val:,.2f}",
                    "m3": f"{(Decimal(getattr(et, 'volume', 0) or 0) * Decimal(qty)):,.2f}",
                }
            )
            unref_total_val += val

        refined_rows = []
        total_val = Decimal("0")
        total_m3 = Decimal("0")
        for tid, qty in refined_rows_src:
            et = type_map.get(int(tid))
            if not et:
                continue
            up = price_input(int(tid), input_basis)
            val = up * Decimal(qty)
            vol_unit = Decimal(getattr(et, "volume", 0) or 0)
            refined_rows.append(
                {
                    "type_id": int(tid),
                    "type_name": et.name,
                    "qty": int(qty),
                    "unit_price": f"{up:,.2f}",
                    "value": f"{val:,.2f}",
                    "m3": f"{(vol_unit * Decimal(qty)):,.2f}",
                }
            )
            total_val += val
            total_m3 += vol_unit * Decimal(qty)

        me_pct = me_bonus_pct(rig_me, facility_location)
        te_pct = te_bonus_pct(rig_te, facility_location)
        stax_pct = sales_tax_pct(accounting_level)

        def _price_in(tid: int) -> Decimal:
            return price_input(int(tid), input_basis)

        def _price_out(tid: int) -> Decimal:
            return price_output(int(tid), output_basis)

        priced_plans = []
        opp_produced: Dict[int, int] = {}

        for p in plans_raw:
            rx = p.get("reaction")
            name = (rx.name if rx and getattr(rx, "name", None) else None) or p.get("name") or f"Reaction {getattr(rx, 'blueprint_type_id', 'N/A')}"
            per_run_reqs_base = {int(k): int(v) for k, v in (p.get("per_run_requirements") or {}).items()}
            per_run_reqs = apply_me_to_requirements(per_run_reqs_base, me_pct)
            per_run_prods = {int(k): int(v) for k, v in (p.get("per_run_products") or {}).items()}
            time_per_run_seconds = int(
                effective_time_seconds(
                    (rx.time_seconds if rx else p.get("time_seconds", 0)),
                    reaction_skill_level,
                    facility_size,
                    te_pct,
                )
            )
            caps_all = []
            for tid, need in per_run_reqs.items():
                if need <= 0 or is_fuel_id(type_map, int(tid)):
                    continue
                have = int(stock.get(tid, 0))
                caps_all.append(have // int(need))
            runs_cap = int(min(caps_all) if caps_all else 0)

            for tid, outq in per_run_prods.items():
                if runs_cap > 0:
                    opp_produced[tid] = opp_produced.get(tid, 0) + outq * runs_cap

            products_list = []
            products_value_raw = Decimal("0")
            for tid, per_run_qty in per_run_prods.items():
                qty = per_run_qty * max(runs_cap, 0)
                et = type_map.get(int(tid))
                if not et:
                    continue
                unit = _price_out(int(tid))
                val = unit * Decimal(qty)
                m3 = Decimal(qty) * Decimal(getattr(et, "volume", 0) or 0)
                products_value_raw += val
                products_list.append(
                    {
                        "type_id": int(tid),
                        "type_name": et.name,
                        "qty": int(qty),
                        "unit_price": f"{unit:,.2f}",
                        "value": f"{val:,.2f}",
                        "m3": f"{m3:,.2f}",
                    }
                )
            consumed_list = []
            consumed_cost_raw = Decimal("0")
            for tid, per_run_qty in per_run_reqs.items():
                qty = per_run_qty * max(runs_cap, 0)
                if qty <= 0:
                    continue
                et = type_map.get(int(tid))
                if not et:
                    continue
                unit = _price_in(int(tid))
                val = unit * Decimal(qty)
                m3 = Decimal(qty) * Decimal(getattr(et, "volume", 0) or 0)
                consumed_cost_raw += val
                consumed_list.append(
                    {
                        "type_id": int(tid),
                        "type_name": et.name,
                        "qty": int(qty),
                        "unit_price": f"{unit:,.2f}",
                        "value": f"{val:,.2f}",
                        "m3": f"{m3:,.2f}",
                    }
                )
            missing_cost_raw = Decimal("0")
            for tid, need_per_run in per_run_reqs.items():
                have_now = int(stock.get(tid, 0))
                needed_total = need_per_run * max(runs_cap, 0)
                lack = max(needed_total - have_now, 0)
                if lack > 0:
                    unit = _price_in(int(tid))
                    base = unit * Decimal(lack)
                    missing_cost_raw += base * (Decimal("1") + (broker_fee_pct / Decimal("100")))
            if output_basis == "buy":
                produced_net = products_value_raw * (Decimal("1") - broker_fee_pct / Decimal("100"))
            else:
                out_fee_rate = (broker_fee_pct + stax_pct) / Decimal("100")
                produced_net = products_value_raw * (Decimal("1") - out_fee_rate)
            facility_fees_inputs = consumed_cost_raw * ((scc_pct + facility_tax_pct + cost_index_pct) / Decimal("100"))
            priced_plans.append(
                {
                    "name": name,
                    "runs": runs_cap,
                    "products": products_list,
                    "consumed": consumed_list,
                    "products_value": f"{products_value_raw:,.2f}",
                    "products_value_raw": f"{products_value_raw}",
                    "produced_net": f"{produced_net}",
                    "missing_cost": f"{missing_cost_raw:,.2f}",
                    "fees_inputs": f"{facility_fees_inputs}",
                    "per_run_requirements": per_run_reqs,
                    "per_run_products": per_run_prods,
                    "time_per_run_seconds": time_per_run_seconds,
                    "time_per_run_str": fmt_duration(time_per_run_seconds),
                    "have_any": bool(p.get("have_any")),
                    "blueprint_type_id": getattr(rx, "blueprint_type_id", p.get("blueprint_type_id")),
                    "raw": {
                        "products_value": products_value_raw,
                        "produced_net": produced_net,
                        "missing_cost": missing_cost_raw,
                        "fees_inputs": facility_fees_inputs,
                    },
                }
            )

        def build_step(
            plan: dict,
            runs: int,
            current_stock: Dict[int, int],
            cum_profit: Decimal,
            supplemental_supply: Dict[int, int] | None = None,
        ):
            per_run_reqs = plan["per_run_requirements"]
            per_run_prods = plan["per_run_products"]
            inputs = []
            consumed_cost_raw = Decimal("0")
            have_val_sum = Decimal("0")
            need_val_sum = Decimal("0")
            m3_total_sum = Decimal("0")
            m3_need_sum = Decimal("0")
            stock_val_sum = Decimal("0")

            supplemental_supply = {int(k): int(v) for k, v in (supplemental_supply or {}).items()}

            display_target_runs = 0
            for _tid, _need in per_run_reqs.items():
                if int(_need) <= 0:
                    continue
                t_i = int(_tid)
                et_i = type_map.get(t_i)
                if et_i and "fuel block" in (et_i.name or "").lower():
                    continue
                total_avail = int(current_stock.get(t_i, 0)) + int(supplemental_supply.get(t_i, 0))
                cap_i = total_avail // int(_need) if int(_need) > 0 else 0
                if cap_i > display_target_runs:
                    display_target_runs = cap_i

            for tid, need_per_run in per_run_reqs.items():
                have_now = int(current_stock.get(int(tid), 0))
                et = type_map.get(int(tid))

                if not et:
                    continue

                unit = _price_in(int(tid))
                required_total = need_per_run * runs
                display_required_total = need_per_run * display_target_runs
                from_children = min(int(supplemental_supply.get(int(tid), 0)), required_total)

                if from_children:
                    supplemental_supply[int(tid)] = max(0, int(supplemental_supply[int(tid)]) - from_children)

                remain_after_children = required_total - from_children
                from_stock = min(have_now, remain_after_children)
                have_used = from_children + from_stock

                need_missing_display = max(display_required_total - have_used, 0)
                missing_val_with_broker = unit * Decimal(need_missing_display) * (
                    Decimal("1") + (broker_fee_pct / Decimal("100"))
                )
                m3_per_run = Decimal(need_per_run) * Decimal(getattr(et, "volume", 0) or 0)
                m3_total = Decimal(required_total) * Decimal(getattr(et, "volume", 0) or 0)
                m3_need = Decimal(need_missing_display) * Decimal(getattr(et, "volume", 0) or 0)

                is_fuel = is_fuel_id(type_map, int(tid)) or ("fuel block" in (et.name or "").lower())

                if use_buyback and from_stock > 0 and not is_fuel:
                    unit_stock_eff = _buyback_unit(int(tid))
                else:
                    unit_stock_eff = unit

                have_val_children = unit * Decimal(from_children)
                have_val_stock = unit_stock_eff * Decimal(from_stock)
                have_val = have_val_children + have_val_stock

                buyback_value_str = (
                    f"{(unit_stock_eff * Decimal(from_stock)):.2f}"
                    if (use_buyback and from_stock > 0 and not is_fuel)
                    else None
                )

                stock_val_sum += have_val_stock

                inputs.append(
                    {
                        "name": et.name if et else str(tid),
                        "need_per_run": int(need_per_run),
                        "have": int(have_used),
                        "total_need": int(required_total),
                        "need_missing": int(need_missing_display),
                        "unit_price": f"{unit:,.2f}",
                        "have_value": f"{have_val:,.2f}",
                        "need_value": f"{missing_val_with_broker:,.2f}",
                        "m3_per_run": f"{m3_per_run:,.2f}",
                        "m3_total": f"{m3_total:,.2f}",
                        "m3_need": f"{m3_need:,.2f}",
                        "from_children": int(from_children),
                        "from_stock": int(from_stock),
                        "produced": False,
                        "buyback_value": buyback_value_str,
                    }
                )
                consumed_cost_raw += (unit * Decimal(from_children)) + (unit_stock_eff * Decimal(from_stock))
                current_stock[int(tid)] = max(0, have_now - from_stock)
                have_val_sum += have_val
                need_val_sum += missing_val_with_broker
                m3_total_sum += m3_total
                m3_need_sum += m3_need

            produced_qty_display = 0
            produced_value_display = Decimal("0")
            produced_volume_display = Decimal("0")
            product_name = ""
            for tid, out_per_run in per_run_prods.items():
                qty_actual = out_per_run * runs
                qty_display = out_per_run * display_target_runs
                etp = type_map.get(int(tid))
                if not etp:
                    continue
                unit_out = _price_out(int(tid))
                produced_value_display += unit_out * Decimal(qty_display)
                produced_volume_display += Decimal(qty_display) * Decimal(getattr(etp, "volume", 0) or 0)
                produced_qty_display += qty_display
                product_name = etp.name if etp else str(tid)
                current_stock[int(tid)] = current_stock.get(int(tid), 0) + qty_actual

            if output_basis == "buy":
                produced_net = produced_value_display * (Decimal("1") - broker_fee_pct / Decimal("100"))
            else:
                out_fee_rate = (broker_fee_pct + stax_pct) / Decimal("100")
                produced_net = produced_value_display * (Decimal("1") - out_fee_rate)

            fees_inputs = consumed_cost_raw * ((scc_pct + facility_tax_pct + cost_index_pct) / Decimal("100"))
            step_profit = produced_net - fees_inputs - need_val_sum - stock_val_sum
            cum_profit_next = cum_profit + step_profit
            step_time_seconds = int(runs * plan.get("time_per_run_seconds", 0))

            step = {
                "kind": "reaction",
                "title": plan["name"],
                "runs": runs,
                "inputs": inputs,
                "product_name": product_name,
                "produced_qty": produced_qty_display,
                "produced_value": produced_value_display,
                "produced_volume": produced_volume_display,
                "value_have": have_val_sum,
                "value_need": need_val_sum,
                "fees": {"broker": Decimal("0"), "sales_tax": fees_inputs},
                "fees_display": f"{fees_inputs:,.2f}",
                "cumulative_profit": cum_profit_next,
                "cumulative_profit_display": f"{cum_profit_next:,.2f}",
                "step_profit": step_profit,
                "step_profit_display": f"{step_profit:,.2f}",
                "children": [],
                "time_total_seconds": step_time_seconds,
                "time_total_str": fmt_duration(step_time_seconds),
                "input_totals": {
                    "have_value": f"{have_val_sum:,.2f}",
                    "need_value": f"{need_val_sum:,.2f}",
                    "m3_total": f"{m3_total_sum:,.2f}",
                    "m3_need_total": f"{m3_need_sum:,.2f}",
                    "fees": f"{fees_inputs:,.2f}",
                },
                "product_stats": {
                    "value": f"{produced_value_display:,.2f}",
                    "m3": f"{produced_volume_display:,.2f}",
                    "isk_per_m3": f"{(produced_value_display / produced_volume_display):,.2f}"
                    if produced_volume_display > 0
                    else "0.00",
                },
                "product_ids": [int(t) for t in per_run_prods.keys()],
                "requirement_ids": [int(t) for t in per_run_reqs.keys()],
                "stock_value_used": f"{stock_val_sum:,.2f}",
                "buyback_value": (
                    f"{(unit_stock_eff * Decimal(from_stock)):.2f}" if (use_buyback and from_stock > 0) else None
                ),
            }
            return step, current_stock, cum_profit_next

        goal_plans: List[dict] = []
        candidates = []
        seen_goal_bp = set()
        for plan in priced_plans:
            has_any = any(
                int(stock.get(int(t), 0)) > 0 and not is_fuel_id(type_map, int(t))
                for t, n in plan["per_run_requirements"].items()
                if int(n) > 0
            )
            can_be_fed = False
            if not has_any:
                parent_inputs = {int(t) for t, n in plan["per_run_requirements"].items() if int(n) > 0}
                for cand in priced_plans:
                    if cand is plan:
                        continue
                    cand_prods = {int(t) for t in (cand.get("per_run_products") or {}).keys()}
                    if parent_inputs & cand_prods:
                        rcap = runcap_with_present(stock, cand["per_run_requirements"], type_map)
                        if rcap > 0:
                            can_be_fed = True
                            break
            if not (has_any or can_be_fed):
                continue
            bp = plan.get("blueprint_type_id") or id(plan)
            if bp in seen_goal_bp:
                continue
            seen_goal_bp.add(bp)
            loss = self_recovery_loss(plan, unrefined_refine_rate, type_map)
            candidates.append((produces_unrefined(plan, type_map), loss, plan))

        for _is_unref, _loss, plan in sorted(candidates, key=lambda x: (x[0], x[1])):
            goal_plans.append(plan)

        chains_raw: List[dict] = []
        virtual_limit = 50

        for gp in goal_plans:
            if len(chains_raw) >= virtual_limit:
                break

            cur = dict(stock)
            profit = Decimal("0")

            feeders = find_feeders_for_parent(gp, priced_plans, type_map, max_count=2)
            feeder_supply: Dict[int, int] = {}
            rendered: List[dict] = []
            cur_after_step1 = dict(cur)
            feeder_steps_for_parent: List[dict] = []

            for fd in feeders:
                r_fd = runcap_with_present(cur_after_step1, fd["per_run_requirements"], type_map)
                if r_fd <= 0:
                    continue
                step_fd, cur_after_step1, profit = build_step(
                    fd, r_fd, cur_after_step1, profit, supplemental_supply=None
                )
                step_fd["is_feeder"] = True
                produced_map = {int(t): int(q * r_fd) for t, q in (fd.get("per_run_products") or {}).items()}
                add_refined, used_unref = reprocess_unrefined_in_stock(produced_map, unrefined_refine_rate, type_map)
                if add_refined:
                    for utid, uqty in used_unref.items():
                        cur_after_step1[int(utid)] = max(0, int(cur_after_step1.get(int(utid), 0)) - int(uqty))
                    add_supply(feeder_supply, add_refined)
                    re_fd = build_reprocess_step(used_unref, add_refined, type_map, input_basis, output_basis)
                    re_fd["cumulative_profit"] = profit
                    re_fd["cumulative_profit_display"] = f"{profit:,.2f}"
                    re_fd["is_feeder"] = True
                    feeder_steps_for_parent.append(step_fd)
                    feeder_steps_for_parent.append(re_fd)
                else:
                    feeder_steps_for_parent.append(step_fd)
                    add_supply(feeder_supply, produced_map)
                    for _tid, _q in produced_map.items():
                        cur_after_step1[int(_tid)] = max(0, int(cur_after_step1.get(int(_tid), 0)) - int(_q))

            for _fs in feeder_steps_for_parent:
                rendered.append(_fs)

            r1 = runcap_with_supply(cur_after_step1, gp["per_run_requirements"], feeder_supply, type_map)
            if r1 <= 0:
                continue

            step1, cur_after_step1, profit = build_step(
                gp, r1, cur_after_step1, profit, supplemental_supply=feeder_supply
            )
            step1["children"] = list(feeder_steps_for_parent or [])
            step1["has_children"] = bool(step1["children"])
            step1_products = {int(t): int(q * r1) for t, q in gp["per_run_products"].items()}
            refined_add, unref_used = reprocess_unrefined_in_stock(step1_products, unrefined_refine_rate, type_map)
            rendered.append(step1)
            rendered[-1]["children"] = step1["children"]
            rendered[-1]["has_children"] = step1["has_children"]

            def _would_self_loop(refined_from_step: Dict[int, int], prev_plan: dict, stock_snapshot: Dict[int, int]) -> bool:
                if not refined_from_step:
                    return False
                prev_inputs = {int(t) for t, n in prev_plan["per_run_requirements"].items() if int(n) > 0}
                for cand in priced_plans:
                    if cand is prev_plan:
                        continue
                    rcap = runcap_with_present(stock_snapshot, cand["per_run_requirements"], type_map)
                    if rcap <= 0:
                        continue
                    for tid, need in cand["per_run_requirements"].items():
                        t = int(tid)
                        if is_fuel_id(type_map, t) or int(need) <= 0:
                            continue
                        if t in prev_inputs and t in refined_from_step:
                            return True
                return False

            if _would_self_loop(refined_add, gp, cur_after_step1):
                continue

            if refined_add:
                for utid, uqty in unref_used.items():
                    cur_after_step1[int(utid)] = max(0, int(cur_after_step1.get(int(utid), 0)) - int(uqty))
                for rtid, rqty in refined_add.items():
                    cur_after_step1[int(rtid)] = int(cur_after_step1.get(int(rtid), 0)) + int(rqty)

                re_step = build_reprocess_step(unrefined_used=unref_used, refined_add=refined_add, type_map=type_map, input_basis=input_basis, output_basis=output_basis)
                re_step["cumulative_profit"] = profit
                re_step["cumulative_profit_display"] = f"{profit:,.2f}"
                rendered.append(re_step)
                prev_products = {int(t) for t in refined_add.keys() if not is_fuel_id(type_map, int(t))}
            else:
                prev_products = {int(t) for t in gp["per_run_products"].keys() if not is_fuel_id(type_map, int(t))}

            picked_any = False
            best = None
            best_key = None
            for p2 in priced_plans:
                if p2 is gp:
                    continue
                if not consumes_any_of(p2, prev_products, type_map):
                    continue
                if has_refined_already(p2, cur_after_step1, type_map):
                    continue
                r2 = runcap_with_present(cur_after_step1, p2["per_run_requirements"], type_map)
                if r2 <= 0:
                    continue
                key = (produces_unrefined(p2, type_map), self_recovery_loss(p2, unrefined_refine_rate, type_map))
                if best is None or key < best_key:
                    best = (p2, r2)
                    best_key = key

            if best:
                p2, r2 = best
                cur2 = dict(cur_after_step1)
                step2, cur_after2, profit2 = build_step(p2, r2, cur2, profit)
                rendered.append(step2)
                picked_any = True

                p2_products = {int(t): int(q * r2) for t, q in p2["per_run_products"].items()}
                refined_add_2, unref_used_2 = reprocess_unrefined_in_stock(p2_products, unrefined_refine_rate, type_map)
                if refined_add_2:
                    for utid, uqty in unref_used_2.items():
                        cur_after2[int(utid)] = max(0, int(cur_after2.get(int(utid), 0)) - int(uqty))
                    for rtid, rqty in refined_add_2.items():
                        cur_after2[int(rtid)] = int(cur_after2.get(int(rtid), 0)) + int(rqty)

                    re_step_2 = build_reprocess_step(unref_used_2, refined_add_2, type_map, input_basis, output_basis)
                    re_step_2["cumulative_profit"] = profit2
                    re_step_2["cumulative_profit_display"] = f"{profit2:,.2f}"
                    rendered.append(re_step_2)
                    next_allowed = {int(t) for t in refined_add_2.keys() if not is_fuel_id(type_map, int(t))}
                else:
                    next_allowed = {int(t) for t in p2["per_run_products"].keys() if not is_fuel_id(type_map, int(t))}

                depth = 2
                cur_stock = dict(cur_after2)
                cur_profit = profit2
                while depth < 4:
                    bestN = None
                    bestN_key = None
                    for pn in priced_plans:
                        if not consumes_any_of(pn, next_allowed, type_map):
                            continue
                        if has_refined_already(pn, cur_stock, type_map):
                            continue

                        def _passes_self_loop_guard_deep(
                            plan_next: dict,
                            recovered_add_prev: Dict[int, int],
                            prev_step_plan: dict,
                            stock_snapshot: Dict[int, int],
                        ) -> bool:
                            if not recovered_add_prev:
                                return True
                            prev_inputs_set = {
                                int(t) for t, n in prev_step_plan["per_run_requirements"].items() if int(n) > 0
                            }
                            rcap_local = runcap_with_present(stock_snapshot, plan_next["per_run_requirements"], type_map)
                            if rcap_local <= 0:
                                return False
                            for t, need in plan_next["per_run_requirements"].items():
                                t_i = int(t)
                                if is_fuel_id(type_map, t_i):
                                    continue
                                if t_i in prev_inputs_set and t_i in recovered_add_prev:
                                    need_total = int(need) * rcap_local
                                    recovered_total = int(recovered_add_prev.get(t_i, 0))
                                    if recovered_total < need_total:
                                        return False
                            return True

                        if not _passes_self_loop_guard_deep(
                            pn, refined_add_2 if depth == 2 else refined_add_N, p2 if depth == 2 else pn, cur_stock
                        ):
                            continue

                        rN = runcap_with_present(cur_stock, pn["per_run_requirements"], type_map)
                        if rN <= 0:
                            continue
                        keyN = (produces_unrefined(pn, type_map), self_recovery_loss(pn, unrefined_refine_rate, type_map))
                        if bestN is None or keyN < bestN_key:
                            bestN = (pn, rN)
                            bestN_key = keyN

                    if not bestN:
                        break

                    pn, rN = bestN
                    cur_tmp = dict(cur_stock)
                    stepN, cur_afterN, profitN = build_step(pn, rN, cur_tmp, cur_profit)
                    rendered.append(stepN)

                    pn_products = {int(t): int(q * rN) for t, q in pn["per_run_products"].items()}
                    refined_add_N, unref_used_N = reprocess_unrefined_in_stock(pn_products, unrefined_refine_rate, type_map)
                    if refined_add_N:
                        for utid, uqty in unref_used_N.items():
                            cur_afterN[int(utid)] = max(0, int(cur_afterN.get(int(utid), 0)) - int(uqty))
                        for rtid, rqty in refined_add_N.items():
                            cur_afterN[int(rtid)] = int(cur_afterN.get(int(rtid), 0)) + int(rqty)

                        re_step_N = build_reprocess_step(
                            unrefined_used=unref_used_N, refined_add=refined_add_N, type_map=type_map, input_basis=input_basis, output_basis=output_basis
                        )
                        re_step_N["cumulative_profit"] = profitN
                        re_step_N["cumulative_profit_display"] = f"{profitN:,.2f}"
                        rendered.append(re_step_N)
                        next_allowed = {int(t) for t in refined_add_N.keys() if not is_fuel_id(type_map, int(t))}
                    else:
                        next_allowed = {int(t) for t in pn["per_run_products"].keys() if not is_fuel_id(type_map, int(t))}

                    cur_stock = cur_afterN
                    cur_profit = profitN
                    depth += 1

            last_reaction_step = None
            for st in reversed(rendered):
                if st.get("kind") == "reaction":
                    last_reaction_step = st
                    break
            if last_reaction_step:
                final_value = Decimal(last_reaction_step["product_stats"]["value"].replace(",", ""))
                final_m3 = Decimal(last_reaction_step["product_stats"]["m3"].replace(",", ""))
            else:
                final_value = Decimal("0")
                final_m3 = Decimal("0")
            final_fees = sum(Decimal(s["fees_display"].replace(",", "")) for s in rendered)

            total_needed_m3 = sum(dec_from(step.get("input_totals", {}).get("m3_need_total", "0")) for step in rendered)
            total_needed_cost = sum(dec_from(step.get("input_totals", {}).get("need_value", "0")) for step in rendered)
            total_stock_value_used = sum(dec_from(s.get("stock_value_used", "0")) for s in rendered)
            total_time_seconds = sum(s.get("time_total_seconds", 0) for s in rendered)
            final_profit = (final_value - final_fees - total_needed_cost - total_stock_value_used) if rendered else Decimal("0")
            debug_chain = {
                "notes": "Final Profit = Final Value − Final Fees − Total Need Cost − Stock Value Used. "
                         "Final Fees = ∑(per-step input fees). Output side uses broker only for Buy, broker+sales tax for Sell.",
                "variables": {
                    "total_needed_cost": f"{total_needed_cost:,.2f}",
                    "total_stock_value_used": f"{total_stock_value_used:,.2f}",
                    "final_value_gross": f"{final_value:,.2f}",
                    "sum_step_fees_inputs": f"{final_fees:,.2f}",
                    "scc_pct": f"{scc_pct:.2f}%",
                    "facility_tax_pct": f"{facility_tax_pct:.2f}%",
                    "cost_index_pct": f"{cost_index_pct:.3f}%",
                    "broker_fee_pct": f"{broker_fee_pct:.2f}%",
                    "sales_tax_pct": f"{stax_pct:.2f}%",
                    "output_price_basis": output_basis.title(),
                },
                "formulas": {
                    "per_step_input_fees": f"Per-step input fees = Consumed Cost × "
                                           f"({scc_pct:.2f}% + {facility_tax_pct:.2f}% + {cost_index_pct:.3f}%) "
                                           f"→ Final Fees = ∑ steps = {final_fees:,.2f}",
                    "produced_net_buy": f"Buy: {final_value:,.2f} × (1 − {broker_fee_pct:.2f}%) = "
                                        f"{(final_value * (Decimal('1') - broker_fee_pct / Decimal('100'))):,.2f}",
                    "produced_net_sell": f"Sell: {final_value:,.2f} × (1 − ({broker_fee_pct:.2f}% + {stax_pct:.2f}%)) = "
                                         f"{(final_value * (Decimal('1') - (broker_fee_pct + stax_pct) / Decimal('100'))):,.2f}",
                    "final_profit": "Final Profit = Final Value − Final Fees − Total Need Cost − Stock Value Used",
                    "final_profit_numeric": f"{final_value:,.2f} − {final_fees:,.2f} − "
                                            f"{total_needed_cost:,.2f} − {total_stock_value_used:,.2f} = "
                                            f"{final_profit:,.2f}",
                },
            }
            final_profit_unformatted = final_profit
            profit_margin = (final_profit / (final_value - final_fees)) * 100 if final_value > 0 else 0
            profit_relative = (final_profit / total_needed_cost) * 100 if total_needed_cost > 0 else 0
            input_cost_share_total_value = (total_needed_cost / final_value) * 100 if final_value > 0 else 0
            profit_per_m3 = (final_profit / final_m3) if final_m3 > 0 else 0
            cost_per_m3 = (total_needed_cost / final_m3) if final_m3 > 0 else 0

            end_names: List[str] = []
            for st in reversed(rendered):
                if st.get("kind") == "reaction":
                    for pid in st.get("product_ids", []):
                        etn = type_map.get(int(pid)).name if type_map.get(int(pid)) else None
                        if etn:
                            end_names.append(etn)
                    if not end_names:
                        end_names.append(st.get("title") or "Reaction Chain")
                    break
            end_name = ", ".join(end_names) if end_names else "Reaction Chain"

            for s in rendered:
                s["is_feeder"] = bool(s.get("is_feeder", False))
            for i, s in enumerate(rendered):
                next_is_feeder = (i + 1 < len(rendered)) and bool(rendered[i + 1].get("is_feeder", False))
                s["show_arrow_after"] = not (s["is_feeder"] and next_is_feeder)

            chains_raw.append(
                {
                    "end_product_name": end_name,
                    "steps": rendered,
                    "final_value": f"{final_value:,.2f}",
                    "final_volume": f"{final_m3:,.2f}",
                    "final_isk_per_m3": f"{(final_value / final_m3):,.2f}" if final_m3 > 0 else "0.00",
                    "final_fees": f"{final_fees:,.2f}",
                    "final_profit_unformatted": final_profit_unformatted,
                    "final_profit": f"{final_profit:,.2f}",
                    "final_need_m3": f"{total_needed_m3:,.2f}",
                    "final_need_cost": f"{total_needed_cost:,.2f}",
                    "total_time_seconds": total_time_seconds,
                    "total_time_str": fmt_duration(total_time_seconds),
                    "profit_margin": f"{profit_margin:.2f}",
                    "profit_margin_unformatted": profit_margin,
                    "profit_relative": f"{profit_relative:.2f}",
                    "profit_relative_unformatted": profit_relative,
                    "input_cost_share_total_value": f"{input_cost_share_total_value:.2f}",
                    "profit_per_m3": f"{profit_per_m3:.2f}",
                    "profit_per_m3_unformatted": profit_per_m3,
                    "cost_per_m3": f"{cost_per_m3:.2f}",
                    "debug_fees_explained": debug_chain,
                }
            )

        sort_key = request.GET.get("sort") or "profit"

        def sort_fn(c):
            if sort_key == "name":
                return (c["end_product_name"].lower(),)
            if sort_key == "value":
                return (Decimal(c["final_value"].replace(",", "")), Decimal(c["final_profit"].replace(",", "")))
            return (Decimal(c["final_profit"].replace(",", "")), Decimal(c["final_value"].replace(",", "")))

        chains_sorted = sorted(chains_raw, key=sort_fn, reverse=(sort_key != "name"))
        chain_groups = [(c["end_product_name"], [c]) for c in chains_sorted]
        chains_total_time = sum(c["total_time_seconds"] for c in chains_sorted)

        context = {
            "refine_rate": f"{refine_rate_pct:.2f}%",
            "price_basis": input_basis,
            "refined": refined_rows,
            "refined_totals": {"value": f"{total_val:,.2f}", "m3": f"{total_m3:,.2f}"} if refined_rows else None,
            "plans": priced_plans,
            "suggestions_lvl1": [],
            "suggestions_lvl2": [],
            "chain_groups": chain_groups,
            "suggestions_total_time_str": fmt_duration(0),
            "chains_total_time_str": fmt_duration(chains_total_time),
            "grand_total_time_str": fmt_duration(chains_total_time),
            "direct_inputs": direct_inputs_rows,
            "direct_inputs_totals": {"value": f"{direct_inputs_total:,.2f}", "m3": f"{direct_inputs_total_m3:,.2f}"},
            "selected_system_name": selected_system_name,
            "selected_reaction_index_pct": f"{selected_reaction_index_pct:,.3f}%" if selected_reaction_index_pct is not None else None,
            "unrefinables": unrefinables,
            "unrefinables_total": {"value": f"{unref_total_val:,.2f}"},
        }
        return render(request, "aareactions/result.html", context)
