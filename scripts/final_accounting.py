#!/usr/bin/env python3
"""Accounting FINAL de la migration conversions : pour chaque copie du tracker maître, détecte les
tuiles restées « sur l'ancien » (Iron Law) et CATÉGORISE chaque résidu :
  - 👤 CONSULTANT : la tuile utilise un slot positionnel UNMAPPED/CONFLICT (ou absent) du mapping client
                    -> décision data du consultant (alimente le filtre du handoff).
  - 🔧 COUVERTURE : la tuile garde un slot MAPPÉ en positionnel (cascade-fallback / benchmark / spécial)
                    -> trou outillage NOUS (carte générique dédiée à venir), pas le consultant.

Sorties (migration/) :
  accounting-final.json  : par client + totaux (dashboards visible-100% / résidu)
  residual-blockers.json : [{client, slot}] DISTINCTS qui bloquent réellement un dashboard -> filtre handoff
  coverage-cards.json    : [{client, copy, card_id, name}] = notre dette outillage

Usage : python3 scripts/final_accounting.py
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from archive_collections import connect_resilient
import conv_lib, special_cards_lib as scl
from migrate_dashboard_full import load_inputs
REPO = Path(__file__).resolve().parent.parent


def _dcs(d): return d.get("dashcards") or d.get("ordered_cards") or []


def main():
    mb = connect_resilient()
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
            try:
                card = mb.get(f"/api/card/{cid}")
                sql, _ = conv_lib.native_and_tags(card)
                card_cache[cid] = (conv_lib.old_conversion_columns(sql), (card or {}).get("name", "")[:50])
            except Exception:
                card_cache[cid] = (set(), "")
        return card_cache[cid]

    acc = {}            # client -> {dash:set, v100:int, residue:int}
    blockers = set()    # (client, slot)
    coverage = []       # cartes couverture (slot mappé resté positionnel)
    for e in tracker:
        client = e.get("client"); copy = e.get("copy_id")
        if not copy: continue
        cmap = {int(k): v for k, v in mapping_all.get(client, {}).items()}
        a = acc.setdefault(client, {"dash": 0, "v100": 0, "residue": 0})
        a["dash"] += 1
        try:
            d = mb.get(f"/api/dashboard/{copy}")
        except Exception:
            continue
        on_old = False
        for dc in _dcs(d):
            cid = dc.get("card_id")
            if not cid or cid in special: continue
            cols, cname = card_info(cid)
            if not cols: continue
            on_old = True
            # catégoriser par slot
            for col in cols:
                slot = conv_lib._slot_of(col)
                if slot is None: continue
                nt = cmap.get(slot)
                if nt is None or nt in (conv_lib.UNMAPPED, conv_lib.CONFLICT):
                    blockers.add((client, slot))
                else:
                    coverage.append({"client": client, "copy": copy, "card_id": cid,
                                     "name": cname})
                    break
        if on_old: a["residue"] += 1
        else: a["v100"] += 1

    tot_dash = sum(a["dash"] for a in acc.values())
    tot_v100 = sum(a["v100"] for a in acc.values())
    out = {"clients": len(acc), "dashboards": tot_dash, "visible_100": tot_v100,
           "residu": tot_dash - tot_v100,
           "blockers_consultant": len(blockers), "coverage_cards": len(coverage),
           "par_client": {c: a for c, a in sorted(acc.items())}}
    (REPO / "migration" / "accounting-final.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    (REPO / "migration" / "residual-blockers.json").write_text(
        json.dumps([{"client": c, "slot": s} for c, s in sorted(blockers)], ensure_ascii=False, indent=1))
    # dédup coverage par (client, card_id)
    seen, cov = set(), []
    for x in coverage:
        k = (x["client"], x["card_id"])
        if k not in seen: seen.add(k); cov.append(x)
    (REPO / "migration" / "coverage-cards.json").write_text(json.dumps(cov, ensure_ascii=False, indent=1))
    print(f"ACCOUNTING : {len(acc)} clients | {tot_dash} dashboards | visible-100% {tot_v100} | "
          f"résidu {tot_dash - tot_v100}")
    print(f"  blockers CONSULTANT (client,slot distincts) : {len(blockers)}")
    print(f"  cartes COUVERTURE (dette outil) : {len(cov)}")


if __name__ == "__main__":
    main()
