# file: aareactions/helper.py
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from math import ceil
from typing import Dict, Iterable, List, Tuple, Any
import re
from django.db.models import Sum
from eveuniverse.models import EveType, EveTypeMaterial
from .models import Reaction, ReactionSettings
from .pricing import resolve_price_value

@dataclass(frozen=True)
class ParsedLine:
    evetype: EveType
    quantity: int

@dataclass(frozen=True)
class ParsedItem:
    evetype: EveType
    quantity: int
    category: str

LOCATION_MULT = {"low": Decimal("1.0"), "null": Decimal("1.1"), "wh": Decimal("1.1")}

def _parse_number_token(tok: str) -> int:
    s = tok.strip().replace(",", "").replace("_", "").lower()
    s = re.sub(r"[^\d.kmb\-+]", "", s)
    m = re.fullmatch(r"([\-+]?\d+(?:\.\d+)?)([kmb])?", s)
    if not m:
        s2 = re.sub(r"[^\d\-+]", "", tok)
        try:
            return int(s2)
        except Exception:
            return 0
    num = float(m.group(1))
    suf = m.group(2) or ""
    mult = 1
    if suf == "k":
        mult = 1_000
    elif suf == "m":
        mult = 1_000_000
    elif suf == "b":
        mult = 1_000_000_000
    return int(num * mult)

def _clean_name_fragment(s: str) -> str:
    s = s.strip().strip('"').strip("'")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*[:|,-]\s*$", "", s)
    return s

def parse_input_lines(raw: str) -> List[Tuple[str, int]]:
    if not raw:
        return []
    line_seps = re.compile(r"[;\n\r]+")
    part_seps = re.compile(r"\s{2,}|\t|\|")
    agg: Dict[str, int] = {}

    def add(name: str, qty: int):
        name_clean = _clean_name_fragment(name)
        if not name_clean or qty <= 0:
            return
        agg[name_clean] = agg.get(name_clean, 0) + int(qty)

    for raw_line in line_seps.split(raw):
        line = (raw_line or "").strip()
        if not line:
            continue
        line = line.replace("\t", " ")
        line = re.sub(r"\s+", " ", line).strip()

        m = re.match(r"^(?P<name>.+?)\s*[x×]\s*(?P<qty>[\d,._kKmMbB+-]+)\s*$", line)
        if m:
            add(m.group("name"), _parse_number_token(m.group("qty")))
            continue
        m = re.match(r"^(?P<qty>[\d,._kKmMbB+-]+)\s*[x×]\s*(?P<name>.+?)\s*$", line)
        if m:
            add(m.group("name"), _parse_number_token(m.group("qty")))
            continue
        m = re.match(r"^(?P<name>.+?)\s*[:\-]\s*(?P<qty>[\d,._kKmMbB+-]+)\s*$", line)
        if m:
            add(m.group("name"), _parse_number_token(m.group("qty")))
            continue
        m = re.match(r"^(?P<name>.*\D)\s+(?P<qty>[\d,._kKmMbB+-]+)\s*$", line)
        if m:
            add(m.group("name"), _parse_number_token(m.group("qty")))
            continue
        m = re.match(r"^(?P<qty>[\d,._kKmMbB+-]+)\s+(?P<name>.+?)\s*$", line)
        if m:
            add(m.group("name"), _parse_number_token(m.group("qty")))
            continue

        chunks = part_seps.split(line)
        if len(chunks) > 1:
            for s in chunks:
                s = s.strip()
                if not s:
                    continue
                mm = re.match(r"^(?P<name>.*\D)\s+(?P<qty>[\d,._kKmMbB+-]+)\s*$", s)
                if mm:
                    add(mm.group("name"), _parse_number_token(mm.group("qty")))
                    continue
                if re.fullmatch(r"[\d,._kKmMbB+-]+", s):
                    continue
                add(s, 1)
            continue

        last = None
        for last in re.finditer(r"[\d,._kKmMbB+-]+", line):
            pass
        if last:
            qty = _parse_number_token(last.group(0))
            name = line[: last.start()].strip().rstrip(",").strip()
            if name:
                add(name, qty)
            continue

        add(line, 1)

    return [(name, qty) for name, qty in agg.items()]

def _get_evetype(item: Any) -> EveType:
    return item.evetype if hasattr(item, "evetype") else item[0]

def _get_qty(item: Any) -> int:
    return item.quantity if hasattr(item, "quantity") else int(item[1])

def sales_tax_pct(accounting_level: int) -> Decimal:
    base = Decimal("7.5")
    reduction = Decimal("0.11") * Decimal(accounting_level)
    if reduction > Decimal("1"):
        reduction = Decimal("1")
    return (base * (Decimal("1") - reduction)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

def me_bonus_pct(rig_me: str, location: str) -> Decimal:
    base = Decimal("0")
    if rig_me == "t1":
        base = Decimal("2.0")
    elif rig_me == "t2":
        base = Decimal("2.4")
    return (base * LOCATION_MULT.get(location, Decimal("1.0"))).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

def te_bonus_pct(rig_te: str, location: str) -> Decimal:
    base = Decimal("0")
    if rig_te == "t1":
        base = Decimal("20.0")
    elif rig_te == "t2":
        base = Decimal("24.0")
    return (base * LOCATION_MULT.get(location, Decimal("1.0"))).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

def size_time_bonus_pct(size: str) -> Decimal:
    if size == "large":
        return Decimal("25.0")
    return Decimal("20.0")

def effective_time_seconds(base: int, skill_level: int, size: str, te_pct: Decimal) -> int:
    skill_red = Decimal("0.04") * Decimal(skill_level)
    size_red = (size_time_bonus_pct(size) / Decimal("100"))
    te_red = (te_pct / Decimal("100"))
    t = Decimal(base) * (Decimal("1") - skill_red) * (Decimal("1") - size_red) * (Decimal("1") - te_red)
    return int(t.to_integral_value(rounding=ROUND_HALF_UP))

def apply_me_to_requirements(per_run_requirements: Dict[int, int], me_pct: Decimal) -> Dict[int, int]:
    eff = (Decimal("100") - me_pct) / Decimal("100")
    out: Dict[int, int] = {}
    for tid, base_q in per_run_requirements.items():
        out[int(tid)] = int(ceil(Decimal(base_q) * eff))
    return out

def resolve_types(pairs: Iterable[Tuple[str, int]]) -> List[ParsedLine]:
    by_name: Dict[str, int] = {}
    by_id: Dict[int, int] = {}
    for name_or_id, qty in pairs:
        if not name_or_id:
            continue
        try:
            tid = int(str(name_or_id))
            by_id[tid] = by_id.get(tid, 0) + int(qty)
        except ValueError:
            by_name[name_or_id] = by_name.get(name_or_id, 0) + int(qty)

    qs_name = EveType.objects.filter(name__in=list(by_name.keys())).only(
        "id", "name", "eve_group_id", "portion_size", "volume"
    )
    qs_id = EveType.objects.filter(id__in=list(by_id.keys())).only(
        "id", "name", "eve_group_id", "portion_size", "volume"
    )
    out = []
    for et in qs_name:
        out.append(ParsedLine(evetype=et, quantity=by_name.get(et.name, 0)))
    for et in qs_id:
        out.append(ParsedLine(evetype=et, quantity=by_id.get(et.id, 0)))
    return out

def categorize_items(items: List[ParsedLine]) -> List[ParsedItem]:
    ids = [p.evetype.id for p in items]
    has_materials = set(
        EveTypeMaterial.objects.filter(eve_type_id__in=ids).values_list("eve_type_id", flat=True).distinct()
    )
    reaction_mat_ids = set(Reaction.objects.values_list("materials__type_id", flat=True).distinct())
    out: List[ParsedItem] = []
    for p in items:
        name = (p.evetype.name or "").lower()
        if "fuel block" in name:
            out.append(ParsedItem(p.evetype, p.quantity, "fuel"))
        elif p.evetype.id in reaction_mat_ids:
            out.append(ParsedItem(p.evetype, p.quantity, "material"))
        elif p.evetype.id in has_materials:
            out.append(ParsedItem(p.evetype, p.quantity, "refine"))
        else:
            continue
    return out

def filter_by_settings(items: List[ParsedItem], settings: ReactionSettings) -> List[ParsedItem]:
    return items

def _is_unrefined_name(name: str) -> bool:
    return bool(name) and name.lower().startswith("unrefined ")

def refine_from_inputs(
    items: List[ParsedItem],
    refine_rate: Decimal,
    unrefined_refine_rate: Decimal | None = None,
) -> Tuple[Dict[int, int], List[Tuple[int, int]]]:
    refinables = [p for p in items if p.category == "refine"]
    refined: Dict[int, int] = {}
    if refinables:
        type_ids = [p.evetype.id for p in refinables]
        mats = (
            EveTypeMaterial.objects.filter(eve_type_id__in=type_ids)
            .values("eve_type_id", "material_eve_type_id")
            .annotate(total=Sum("quantity"))
        )
        mats_by_source: Dict[int, List[Tuple[int, int]]] = {}
        for m in mats:
            mats_by_source.setdefault(int(m["eve_type_id"]), []).append(
                (int(m["material_eve_type_id"]), int(m["total"]))
            )
        for p in refinables:
            rate = refine_rate
            if unrefined_refine_rate is not None and _is_unrefined_name(p.evetype.name or ""):
                rate = unrefined_refine_rate
            portion = Decimal(p.evetype.portion_size or 1)
            portions = (Decimal(p.quantity) / portion) if portion > 0 else Decimal(p.quantity)
            for mt, per_portion in mats_by_source.get(p.evetype.id, []):
                base = Decimal(per_portion) * portions
                produced = (base * rate).to_integral_value(rounding=ROUND_DOWN)
                if produced <= 0:
                    continue
                refined[mt] = refined.get(mt, 0) + int(produced)
    rows: List[Tuple[int, int]] = [(tid, qty) for tid, qty in refined.items()]
    return refined, rows

def build_initial_stock(
    items: List[ParsedItem],
    refine_rate: Decimal,
    unrefined_refine_rate: Decimal | None = None,
) -> Tuple[Dict[int, int], List[Tuple[int, int]]]:
    stock: Dict[int, int] = {}
    refined, refined_rows = refine_from_inputs(items, refine_rate, unrefined_refine_rate)
    for tid, qty in refined.items():
        stock[tid] = stock.get(tid, 0) + int(qty)
    for p in items:
        if p.category in ("material", "fuel"):
            stock[p.evetype.id] = stock.get(p.evetype.id, 0) + int(p.quantity)
    return stock, refined_rows

def plan_reactions_once(stock: Dict[int, int]) -> Tuple[List[dict], Dict[int, int]]:
    plans: List[dict] = []
    remaining = dict(stock)
    reactions = Reaction.objects.all().prefetch_related("materials__type", "products__type").only(
        "id", "name", "blueprint_type_id", "time_seconds"
    )
    for rx in reactions:
        reqs: Dict[int, int] = {}
        prods: Dict[int, int] = {}
        for m in rx.materials.all():
            reqs[m.type_id] = int(m.quantity)
        for p in rx.products.all():
            prods[p.type_id] = int(p.quantity)
        caps = []
        for tid, need in reqs.items():
            have = int(remaining.get(tid, 0))
            if need <= 0:
                continue
            caps.append(have // need)
        max_runs = int(min(caps) if caps else 0)
        if max_runs <= 0:
            missing: Dict[int, int] = {}
            have_any = False
            for tid, need in reqs.items():
                have = int(remaining.get(tid, 0))
                if have > 0:
                    have_any = True
                missing[tid] = max(need - have, 0)
            plans.append(
                {
                    "reaction": rx,
                    "runs": 0,
                    "products": {},
                    "consumed": {},
                    "missing": missing,
                    "have_any": have_any,
                    "materials_all": reqs,
                    "per_run_requirements": reqs,
                    "per_run_products": prods,
                }
            )
            continue
        consumed: Dict[int, int] = {}
        for tid, need in reqs.items():
            use = need * max_runs
            remaining[tid] = remaining.get(tid, 0) - use
            consumed[tid] = use
        produced: Dict[int, int] = {}
        for tid, outq in prods.items():
            qty = outq * max_runs
            remaining[tid] = remaining.get(tid, 0) + qty
            produced[tid] = qty
        plans.append(
            {
                "reaction": rx,
                "runs": max_runs,
                "products": produced,
                "consumed": consumed,
                "missing": {},
                "have_any": True,
                "materials_all": reqs,
                "per_run_requirements": reqs,
                "per_run_products": prods,
            }
        )
    return plans, remaining

def plan_reactions_with_chain(stock: Dict[int, int]) -> List[dict]:
    plans, _ = plan_reactions_once(stock)
    return plans

def fmt_duration(seconds: int) -> str:
    s = int(max(0, seconds))
    d, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h or d:
        parts.append(f"{h}h")
    if m or h or d:
        parts.append(f"{m}m")
    if s or not parts:
        parts.append(f"{s}s")
    return " ".join(parts)

def is_fuel_id(type_map: Dict[int, EveType], tid: int) -> bool:
    et = type_map.get(int(tid))
    return bool(et and "fuel block" in (et.name or "").lower())

def refined_partner_type_id(type_map: Dict[int, EveType], unrefined_tid: int) -> int | None:
    et = type_map.get(int(unrefined_tid))
    if not et or not _is_unrefined_name(et.name or ""):
        return None
    ref_name = (et.name or "")[len("Unrefined "):]
    for t in type_map.values():
        if (t.name or "") == ref_name:
            return int(t.id)
    try:
        t = EveType.objects.only("id", "name").get(name=ref_name)
        type_map[int(t.id)] = t
        return int(t.id)
    except EveType.DoesNotExist:
        return None

def has_refined_already(plan: dict, stock_map: Dict[int, int], type_map: Dict[int, EveType]) -> bool:
    for tid in (plan.get("per_run_products") or {}).keys():
        rid = refined_partner_type_id(type_map, int(tid))
        if rid is not None and int(stock_map.get(rid, 0)) > 0:
            return True
    return False

def runcap_with_present(stock_map: Dict[int, int], reqs: Dict[int, int], type_map: Dict[int, EveType]) -> int:
    caps = []
    have_any = False
    for tid, need in (reqs or {}).items():
        if int(need) <= 0:
            continue
        if is_fuel_id(type_map, int(tid)):
            continue
        have = int(stock_map.get(int(tid), 0))
        if have > 0:
            have_any = True
            caps.append(have // int(need))
    if not have_any:
        return 0
    return int(min(caps) if caps else 0)

def runcap_with_supply(
    stock_map: Dict[int, int],
    reqs: Dict[int, int],
    supply: Dict[int, int] | None,
    type_map: Dict[int, EveType],
) -> int:
    if not supply:
        return runcap_with_present(stock_map, reqs, type_map)
    merged = dict(stock_map)
    for k, v in (supply or {}).items():
        if v:
            merged[int(k)] = int(merged.get(int(k), 0)) + int(v)
    return runcap_with_present(merged, reqs, type_map)

def price_input(tid: int, price_basis: str) -> Decimal:
    try:
        return resolve_price_value(int(tid), price_basis) or Decimal("0")
    except Exception:
        return Decimal("0")

def price_output(tid: int, price_basis: str) -> Decimal:
    try:
        return resolve_price_value(int(tid), price_basis) or Decimal("0")
    except Exception:
        return Decimal("0")

def add_supply(dst: Dict[int, int], src: Dict[int, int]) -> None:
    for k, v in (src or {}).items():
        if v:
            dst[int(k)] = int(dst.get(int(k), 0)) + int(v)

def find_feeders_for_parent(
    parent_plan: dict,
    priced_plans: List[dict],
    type_map: Dict[int, EveType],
    max_count: int = 2,
) -> List[dict]:
    parent_inputs = {int(t) for t, n in (parent_plan.get("per_run_requirements") or {}).items() if int(n) > 0}
    feeders: List[tuple[int, dict]] = []
    for cand in priced_plans:
        if cand is parent_plan:
            continue
        prods = {int(t) for t in (cand.get("per_run_products") or {}).keys()}
        if any((pid in parent_inputs and not is_fuel_id(type_map, pid)) for pid in prods):
            overlap = sum(1 for pid in prods if pid in parent_inputs)
            feeders.append((overlap, cand))
    feeders.sort(key=lambda x: (-x[0], x[1]["name"]))
    return [c for _, c in feeders[:max_count]]

def reprocess_unrefined_in_stock(
    produced: Dict[int, int],
    refine_rate: Decimal,
    type_map: Dict[int, EveType],
) -> Tuple[Dict[int, int], Dict[int, int]]:
    if not produced:
        return {}, {}
    tids = list({int(t) for t in produced.keys()})
    tmap = {t.id: t for t in EveType.objects.filter(id__in=tids).only("id", "name", "portion_size")}
    unref_ids = [tid for tid in tids if (tmap.get(tid) and _is_unrefined_name(tmap[tid].name or ""))]

    if not unref_ids:
        return {}, {}
    mats = (
        EveTypeMaterial.objects
        .filter(eve_type_id__in=unref_ids)
        .values("eve_type_id", "material_eve_type_id")
        .annotate(total=Sum("quantity"))
    )
    mats_by_unref: Dict[int, List[Tuple[int, int]]] = {}
    material_ids: set[int] = set()
    for m in mats:
        e = int(m["eve_type_id"])
        mt = int(m["material_eve_type_id"])
        q = int(m["total"])
        mats_by_unref.setdefault(e, []).append((mt, q))
        material_ids.add(mt)
    missing = [mid for mid in material_ids if mid not in type_map]
    if missing:
        for t in EveType.objects.filter(id__in=missing).only("id", "name", "volume"):
            type_map[int(t.id)] = t

    add: Dict[int, int] = {}
    used: Dict[int, int] = {}
    for utid in unref_ids:
        qty = int(produced.get(utid, 0))
        if qty <= 0:
            continue
        et = tmap.get(utid)
        portion = Decimal(getattr(et, "portion_size", 1) or 1)
        portions = (Decimal(qty) / portion) if portion > 0 else Decimal(qty)
        for mtid, per_portion in mats_by_unref.get(utid, []):
            base = Decimal(per_portion) * portions
            out_units = (base * refine_rate).to_integral_value(rounding=ROUND_DOWN)
            if out_units > 0:
                add[int(mtid)] = add.get(int(mtid), 0) + int(out_units)
        used[int(utid)] = used.get(int(utid), 0) + qty
    return add, used


def build_reprocess_step(
    unrefined_used: Dict[int, int],
    refined_add: Dict[int, int],
    type_map: Dict[int, EveType],
    input_basis: str,
    output_basis: str,
) -> dict:
    inputs = []
    have_val_sum = Decimal("0")
    m3_total_sum = Decimal("0")
    for tid, total_need in (unrefined_used or {}).items():
        et = type_map.get(int(tid))
        if not et:
            continue
        unit = price_input(int(tid), input_basis)
        have_val = unit * Decimal(total_need)
        m3_total = Decimal(total_need) * Decimal(getattr(et, "volume", 0) or 0)
        inputs.append(
            {
                "name": et.name,
                "need_per_run": int(total_need),
                "have": int(total_need),
                "total_need": int(total_need),
                "need_missing": 0,
                "unit_price": f"{unit:,.2f}",
                "have_value": f"{have_val:,.2f}",
                "need_value": f"{Decimal(0):,.2f}",
                "m3_per_run": f"{m3_total:,.2f}",
                "m3_total": f"{m3_total:,.2f}",
                "produced": False,
            }
        )
        have_val_sum += have_val
        m3_total_sum += m3_total

    outputs = []
    produced_value = Decimal("0")
    produced_volume = Decimal("0")
    product_ids: List[int] = []
    for tid, q in (refined_add or {}).items():
        etp = type_map.get(int(tid))
        if not etp:
            continue
        product_ids.append(int(tid))
        unit_out = price_output(int(tid), output_basis)
        row_val = unit_out * Decimal(q)
        row_vol = Decimal(q) * Decimal(getattr(etp, "volume", 0) or 0)
        produced_value += row_val
        produced_volume += row_vol
        outputs.append(
            {
                "name": etp.name,
                "qty": int(q),
                "unit_price": f"{unit_out:,.2f}",
                "value": f"{row_val:,.2f}",
                "m3": f"{row_vol:,.2f}",
            }
        )

    return {
        "kind": "reprocess",
        "title": "Refined materials",
        "runs": 1,
        "inputs": inputs,
        "outputs": outputs,
        "product_name": "Refined materials",
        "produced_qty": sum((refined_add or {}).values()),
        "produced_value": produced_value,
        "produced_volume": produced_volume,
        "value_have": have_val_sum,
        "value_need": Decimal("0"),
        "fees": {"broker": Decimal("0"), "sales_tax": Decimal("0")},
        "fees_display": f"{Decimal('0'):,.2f}",
        "cumulative_profit": Decimal("0"),
        "cumulative_profit_display": f"{Decimal('0'):,.2f}",
        "time_total_seconds": 0,
        "time_total_str": fmt_duration(0),
        "input_totals": {
            "have_value": f"{have_val_sum:,.2f}",
            "need_value": f"{Decimal('0'):,.2f}",
            "m3_total": f"{m3_total_sum:,.2f}",
            "fees": f"{Decimal('0'):,.2f}",
        },
        "product_stats": {
            "value": f"{produced_value:,.2f}",
            "m3": f"{produced_volume:,.2f}",
            "isk_per_m3": f"{(produced_value / produced_volume):,.2f}" if produced_volume > 0 else "0.00",
        },
        "product_ids": product_ids,
        "requirement_ids": list((unrefined_used or {}).keys()),
    }


def consumes_any_of(plan: dict, allowed_tids: set[int], type_map: Dict[int, EveType]) -> bool:
    for tid, need in (plan.get("per_run_requirements") or {}).items():
        if int(need) <= 0:
            continue
        t = int(tid)
        if is_fuel_id(type_map, t):
            continue
        if t in allowed_tids:
            return True
    return False


def produces_unrefined(plan: dict, type_map: Dict[int, EveType]) -> bool:
    for tid in (plan.get("per_run_products") or {}).keys():
        et = type_map.get(int(tid))
        if et and _is_unrefined_name(et.name or ""):
            return True
    return False


def self_recovery_loss(plan: dict, refine_rate: Decimal, type_map: Dict[int, EveType]) -> int:
    per_run_reqs = {int(k): int(v) for k, v in (plan.get("per_run_requirements") or {}).items()}
    per_run_prods = {int(k): int(v) for k, v in (plan.get("per_run_products") or {}).items()}
    if not per_run_prods or not per_run_reqs:
        return 0
    unref_tids = [int(t) for t in per_run_prods.keys() if (type_map.get(int(t)) and _is_unrefined_name(type_map[int(t)].name or ""))]
    if not unref_tids:
        return 0
    mats = (
        EveTypeMaterial.objects
        .filter(eve_type_id__in=unref_tids)
        .values("eve_type_id", "material_eve_type_id")
        .annotate(total=Sum("quantity"))
    )
    mats_by_unref: Dict[int, List[Tuple[int, int]]] = {}
    for m in mats:
        mats_by_unref.setdefault(int(m["eve_type_id"]), []).append((int(m["material_eve_type_id"]), int(m["total"])))
    recovered: Dict[int, int] = {}
    for utid in unref_tids:
        et = type_map.get(int(utid))
        if not et:
            continue
        portion = Decimal(getattr(et, "portion_size", 1) or 1)
        portions = (Decimal(per_run_prods[utid]) / portion) if portion > 0 else Decimal(per_run_prods[utid])
        for mtid, per_portion in mats_by_unref.get(utid, []):
            base = Decimal(per_portion) * portions
            out_units = (base * refine_rate).to_integral_value(rounding=ROUND_DOWN)
            recovered[int(mtid)] = recovered.get(int(mtid), 0) + int(out_units)
    loss = 0
    for mtid, need in per_run_reqs.items():
        rec = int(recovered.get(int(mtid), 0))
        if rec > 0:
            loss += max(int(need) - rec, 0)
    return loss


def dec_from(s) -> Decimal:
    if isinstance(s, Decimal):
        return s
    if s is None:
        return Decimal("0")
    if isinstance(s, (int, float)):
        return Decimal(str(s))
    return Decimal((s or "0").replace(",", ""))
