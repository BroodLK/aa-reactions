import json
from django.core.management.base import BaseCommand, CommandError
from eveuniverse.models import EveType
from django.db import transaction
from pathlib import Path
from typing import List
from ...models import Reaction, ReactionMaterial, ReactionProduct


class Command(BaseCommand):
    help = "Import reactions"

    def handle(self, *args, **options):
        models_path = Path(__import__("aareactions.models").models.__file__).resolve()
        file_path = models_path.parent / "reactions.jsonl"
        if not file_path.exists():
            raise CommandError(f"reactions.jsonl not found at {file_path}")

        imported = 0
        errors = 0

        with file_path.open("r", encoding="utf-8") as fh, transaction.atomic():
            for idx, raw in enumerate(fh, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as e:
                    errors += 1
                    self.stderr.write(f"Line {idx}: JSON error: {e}")
                    continue

                try:
                    bp_id = int(data.get("blueprintTypeID") or 0)
                    rx_data = (data.get("activities") or {}).get("reaction") or {}
                    time_sec = int(rx_data.get("time") or 0)
                    mats = rx_data.get("materials") or []
                    prods = rx_data.get("products") or []
                except Exception as e:
                    errors += 1
                    self.stderr.write(f"Line {idx}: Parse error: {e}")
                    continue

                if not bp_id:
                    errors += 1
                    self.stderr.write(f"Line {idx}: Missing blueprintTypeID")
                    continue

                needed_type_ids: List[int] = [bp_id] + [int(m["typeID"]) for m in mats if "typeID" in m] + [
                    int(p["typeID"]) for p in prods if "typeID" in p
                ]
                EveType.objects.in_bulk(needed_type_ids)

                reaction, _ = Reaction.objects.update_or_create(
                    blueprint_type_id=bp_id, defaults={"time_seconds": time_sec}
                )
                reaction.name = (
                    EveType.objects.filter(id=bp_id).values_list("name", flat=True).first()
                    or reaction.name
                )
                reaction.save()

                ReactionMaterial.objects.filter(reaction=reaction).delete()
                ReactionProduct.objects.filter(reaction=reaction).delete()

                mat_rows: List[ReactionMaterial] = []
                for m in mats:
                    try:
                        t_id = int(m["typeID"])
                        qty = int(m["quantity"])
                    except Exception:
                        continue
                    et = EveType.objects.filter(id=t_id).first()
                    if not et or qty <= 0:
                        continue
                    mat_rows.append(ReactionMaterial(reaction=reaction, type=et, quantity=qty))

                prod_rows: List[ReactionProduct] = []
                for p in prods:
                    try:
                        t_id = int(p["typeID"])
                        qty = int(p["quantity"])
                    except Exception:
                        continue
                    et = EveType.objects.filter(id=t_id).first()
                    if not et or qty <= 0:
                        continue
                    prod_rows.append(ReactionProduct(reaction=reaction, type=et, quantity=qty))

                if mat_rows:
                    ReactionMaterial.objects.bulk_create(mat_rows, batch_size=1000)
                if prod_rows:
                    ReactionProduct.objects.bulk_create(prod_rows, batch_size=1000)

                imported += 1

        self.stdout.write(self.style.SUCCESS(f"Imported {imported} reactions from {file_path} with {errors} errors"))
