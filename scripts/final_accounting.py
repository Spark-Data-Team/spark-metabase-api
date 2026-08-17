#!/usr/bin/env python3
"""Accounting FINAL de la migration conversions : pour chaque copie du tracker maître, détecte les
tuiles restées « sur l'ancien » (Iron Law) et CATÉGORISE chaque résidu :
  - 👤 CONSULTANT : la tuile utilise un slot positionnel UNMAPPED/CONFLICT (ou absent) du mapping client
                    -> décision data du consultant (alimente le filtre du handoff).
  - 🔧 COUVERTURE : la tuile garde un slot MAPPÉ en positionnel (cascade-fallback / benchmark / spécial)
                    -> trou outillage NOUS (carte générique dédiée à venir), pas le consultant.

Sorties (migration/) :
  accounting-final.json  : par client + totaux (dashboards visible-100% / résidu)
  accounting-copies.json : statut Iron-Law et causes au grain copy_id (entrée du manifeste canonique)
  residual-blockers.json : [{client, slot}] DISTINCTS qui bloquent réellement un dashboard -> filtre handoff
  coverage-cards.json    : [{client, copy, card_id, name}] = notre dette outillage

Usage : python3 scripts/final_accounting.py
"""
import sys, json, time
from contextlib import redirect_stdout
import io
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import conv_lib, special_cards_lib as scl
from migrate_dashboard_full import connect, load_inputs
REPO = Path(__file__).resolve().parent.parent


def _dcs(d): return d.get("dashcards") or d.get("ordered_cards") or []


def dashboard_card_refs(dc):
    """Toutes les cartes consommées par un dashcard, carte principale et séries."""
    if dc.get("card_id"):
        yield "card", dc["card_id"]
    for series in dc.get("series") or []:
        cid = series.get("id") or series.get("card_id")
        if cid:
            yield "series", cid


def fetch_dict(mb, endpoint, retries=3, retry_delay=1):
    """GET Metabase fail-closed : aucune erreur réseau/HTTP ne devient un faux clean."""
    last_error = None
    for attempt in range(max(1, retries)):
        try:
            # Le wrapper valide la session avec /api/user/current avant CHAQUE GET.
            # Une connexion vient d'être authentifiée par ``connect`` : utiliser sa
            # session HTTP directement évite des centaines de round-trips inutiles.
            # Les doubles de tests sans session interne gardent le chemin public.
            if all(hasattr(mb, attr) for attr in ("_http", "domain", "header")):
                response = mb._http.get(
                    mb.domain + endpoint,
                    headers=mb.header,
                    timeout=60,
                )
                if response.status_code in (401, 403):
                    payload = mb.get(endpoint, timeout=60)
                else:
                    response.raise_for_status()
                    payload = response.json()
            else:
                payload = mb.get(endpoint, timeout=60)
            if isinstance(payload, dict):
                return payload
            last_error = RuntimeError(f"réponse non JSON/dict pour {endpoint}: {payload!r}")
        except Exception as exc:
            last_error = exc
        if attempt + 1 < max(1, retries):
            time.sleep(retry_delay * (2 ** attempt))
    raise RuntimeError(f"lecture Metabase impossible après {max(1, retries)} essais: {endpoint}") from last_error


def embedded_cards(dashboard):
    """Cartes complètes déjà embarquées par GET /api/dashboard, primary et series."""
    for dc in _dcs(dashboard):
        card = dc.get("card")
        if isinstance(card, dict) and card.get("id") and card.get("dataset_query"):
            yield card
        for series in dc.get("series") or []:
            candidates = [series, series.get("card") if isinstance(series, dict) else None]
            for candidate in candidates:
                if (isinstance(candidate, dict) and candidate.get("id")
                        and candidate.get("dataset_query")):
                    yield candidate
                    break


def classify_copy(dashboard, client_mapping, card_info, special_ids=None):
    """Retourne le statut Iron-Law détaillé d'une copie déjà chargée.

    ``card_info`` est injecté pour garder cette logique testable et pour permettre au
    caller de dédupliquer les GET Metabase. Une carte peut cumuler une dette consultant
    (slot sans cible sûre) et une dette couverture (autre slot pourtant mappé).
    """
    special_ids = special_ids or set()
    residual_cards = []
    unknown_cards = []
    blocker_slots = set()
    coverage = []
    for dc in _dcs(dashboard):
        for location, cid in dashboard_card_refs(dc):
            if cid in special_ids:
                continue
            info = card_info(cid)
            cols, cname = info[:2]
            opaque = bool(info[2]) if len(info) > 2 else False
            if not cols:
                if opaque:
                    unknown_cards.append({
                        "dashcard_id": dc.get("id"),
                        "card_id": cid,
                        "location": location,
                        "name": cname,
                        "reason": "opaque_snippet_or_source_card",
                    })
                continue
            slots = sorted({
                slot for slot in (conv_lib._slot_of(col) for col in cols)
                if slot is not None
            })
            blocked = sorted(
                slot for slot in slots
                if client_mapping.get(slot) in (None, conv_lib.UNMAPPED, conv_lib.CONFLICT)
            )
            mapped = sorted(set(slots) - set(blocked))
            blocker_slots.update(blocked)
            if mapped:
                coverage.append({
                    "card_id": cid,
                    "location": location,
                    "name": cname,
                    "slots": mapped,
                })
            residual_cards.append({
                "dashcard_id": dc.get("id"),
                "card_id": cid,
                "location": location,
                "name": cname,
                "old_columns": sorted(cols),
                "slots": slots,
                "consultant_slots": blocked,
                "coverage_slots": mapped,
            })
    return {
        "iron_law": (
            "residual" if residual_cards else "unknown" if unknown_cards else "clean"
        ),
        "consultant_slots": sorted(blocker_slots),
        "coverage": coverage,
        "residual_cards": residual_cards,
        "unknown_cards": unknown_cards,
    }


def main():
    # Le client historique affiche encore l'identifiant de session lors de l'auth.
    # L'accounting est un rapport partageable : ne jamais laisser ce secret dans stdout.
    with redirect_stdout(io.StringIO()):
        mb = connect()
    mapping_all, _ = load_inputs()
    tracker = json.loads((REPO / "migration" / "conv-migration-tracker.json").read_text())
    entries = []
    for f in (REPO / "migration").glob("tu-generic-*.json"):
        try: entries.append(json.loads(f.read_text()))
        except Exception: pass
    special = scl.replacement_ids(entries)

    card_cache = {}   # cid -> (colonnes conversion positionnelles, nom) ; 1 seul GET par carte
    def card_info(cid):
        if cid not in card_cache:
            card = fetch_dict(mb, f"/api/card/{cid}")
            sql, _ = conv_lib.native_and_tags(card)
            card_cache[cid] = (
                conv_lib.old_conversion_columns(sql),
                card.get("name", "")[:50],
                conv_lib.has_opaque_refs(sql),
            )
        return card_cache[cid]

    acc = {}            # client -> {dash:set, v100:int, residue:int}
    blockers = set()    # (client, slot)
    coverage = []       # cartes couverture (slot mappé resté positionnel)
    copy_details = []   # état fail-closed au grain copie, consommé par le manifeste canonique
    executable_copies = sum(1 for entry in tracker if entry.get("copy_id"))
    processed_copies = 0
    for e in tracker:
        client = e.get("client"); copy = e.get("copy_id")
        if not copy: continue
        processed_copies += 1
        if processed_copies == 1 or processed_copies % 25 == 0:
            print(
                f"Scan Iron Law: {processed_copies}/{executable_copies} copies…",
                flush=True,
            )
        cmap = {int(k): v for k, v in mapping_all.get(client, {}).items()}
        a = acc.setdefault(client, {"dash": 0, "v100": 0, "residue": 0, "unknown": 0})
        a["dash"] += 1
        d = fetch_dict(mb, f"/api/dashboard/{copy}")
        for embedded in embedded_cards(d):
            embedded_id = int(embedded["id"])
            if embedded_id not in card_cache:
                embedded_sql, _ = conv_lib.native_and_tags(embedded)
                card_cache[embedded_id] = (
                    conv_lib.old_conversion_columns(embedded_sql),
                    embedded.get("name", "")[:50],
                    conv_lib.has_opaque_refs(embedded_sql),
                )
        detail = classify_copy(d, cmap, card_info, special)
        for slot in detail["consultant_slots"]:
            blockers.add((client, slot))
        for item in detail["coverage"]:
            coverage.append({"client": client, "copy": copy, **item})
        causes = []
        if detail["consultant_slots"]:
            causes.append({
                "code": "consultant_mapping_required",
                "category": "consultant",
                "source": "metabase-live",
                "details": {"slots": detail["consultant_slots"]},
            })
        if detail["coverage"]:
            causes.append({
                "code": "conversion_coverage_gap",
                "category": "coverage",
                "source": "metabase-live",
                "details": {
                    "card_ids": sorted({item["card_id"] for item in detail["coverage"]}),
                },
            })
        if detail["unknown_cards"]:
            causes.append({
                "code": "opaque_card_reference",
                "category": "validation",
                "source": "metabase-live",
                "details": {
                    "card_ids": sorted({item["card_id"] for item in detail["unknown_cards"]}),
                },
            })
        copy_details.append({
            "client": client,
            "dashboard": e.get("dashboard"),
            "original_id": e.get("original_id"),
            "copy_id": copy,
            "live_name": d.get("name"),
            "collection_id": d.get("collection_id"),
            "iron_law_status": detail["iron_law"],
            "causes": causes,
            **detail,
        })
        if detail["iron_law"] == "residual":
            a["residue"] += 1
        elif detail["iron_law"] == "unknown":
            a["unknown"] += 1
        else:
            a["v100"] += 1

    # dédup coverage par (client, card_id)
    seen, cov = set(), []
    for x in coverage:
        k = (x["client"], x["card_id"])
        if k not in seen: seen.add(k); cov.append(x)
    tot_dash = sum(a["dash"] for a in acc.values())
    tot_v100 = sum(a["v100"] for a in acc.values())
    tot_residue = sum(a["residue"] for a in acc.values())
    tot_unknown = sum(a["unknown"] for a in acc.values())
    out = {"clients": len(acc), "dashboards": tot_dash, "visible_100": tot_v100,
           "residu": tot_residue, "unknown": tot_unknown,
           "non_complete": tot_residue + tot_unknown,
           "blockers_consultant": len(blockers), "coverage_cards": len(cov),
           "par_client": {c: a for c, a in sorted(acc.items())}}
    (REPO / "migration" / "accounting-final.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    (REPO / "migration" / "accounting-copies.json").write_text(
        json.dumps({"source": "metabase-live", "copies": copy_details}, ensure_ascii=False, indent=1))
    (REPO / "migration" / "residual-blockers.json").write_text(
        json.dumps([{"client": c, "slot": s} for c, s in sorted(blockers)], ensure_ascii=False, indent=1))
    (REPO / "migration" / "coverage-cards.json").write_text(json.dumps(cov, ensure_ascii=False, indent=1))
    print(f"ACCOUNTING : {len(acc)} clients | {tot_dash} dashboards | visible-100% {tot_v100} | "
          f"résidu {tot_residue} | inconnu {tot_unknown}")
    print(f"  blockers CONSULTANT (client,slot distincts) : {len(blockers)}")
    print(f"  cartes COUVERTURE (dette outil) : {len(cov)}")


if __name__ == "__main__":
    main()
