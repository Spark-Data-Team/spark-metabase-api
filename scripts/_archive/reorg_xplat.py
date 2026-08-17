#!/usr/bin/env python3
"""Réorganisation à plat de Cross-platform (collection 214) en 6 familles de métriques.

Opérations :
1. Snapshot pré-vol du sous-arbre 214.
2. Création des 6 collections-familles sous 214.
3. Classification + déplacement de toutes les cartes du sous-arbre vers leur famille.
4. Archivage des sous-collections d'entité devenues vides (1.Account, 2.Campaign,
   3.Adgroup, 4.Ad, et leurs sous-sous-collections).
5. Vérification d'invariant : aucune carte perdue, aucune archivée, aucun
   `dashboard_count` modifié → aucun dashboard client cassé.

Usage : python3 scripts/reorg_xplat.py [--yes]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

from reorg_phase1 import connect, _check  # noqa: E402
from reorg_lib import capture_state, verify_invariant  # noqa: E402

XPLAT_ID = 214
MIGRATION_DIR = REPO_ROOT / "migration"

FAMILIES = [
    ("A. Coûts",
     "CAC, CPA, CPL, CPC, CPM, CPI, CPV, Cost, Spend"),
    ("B. Conversions",
     "CR, CTR, Conversions, Add to cart, ATC, Leads, Purchases, Sign ups, "
     "App installs, Funnel, Thruplays, Hook/Hold rate"),
    ("C. Revenu",
     "Revenue, ROAS, COS, AOV, Average basket, Conversion value"),
    ("D. Trafic",
     "Clicks, Impressions, Views, Reach, Frequency, Search impression share"),
    ("E. Performances",
     "Performances by X, KPI evolution, Account metric, Top ads"),
    ("F. Autres",
     "Cas particuliers : météo, comparatifs stratégiques"),
]

COST_KWS = ['cac', 'cpa', 'cpl', 'cpc', 'cpm', 'cpi', 'cpv', 'cpatc', 'cpe', 'cp',
            'cost', 'spend', 'ncac', 'ncos', 'nroas', 'share of cost']
REVENUE_KWS = ['revenue', 'roas', 'cos', 'aov', 'basket']
CONV_KWS = ['cr', 'ctr', 'conv', 'conversion', 'conversions',
            'add to carts', 'add to cart', 'add_to_cart',
            'atc', 'lead', 'leads', 'purchase', 'purchases', 'sign', 'main', 'ratio',
            'app install', 'app installs', 'app_install', 'app_installs',
            'funnel', 'total install', 'total installs',
            'thruplay', 'thruplays', 'hook', 'hold']
TRAFFIC_KWS = ['click', 'clicks', 'impression', 'impressions', 'view', 'views',
               'visit', 'visits', 'social', 'tweet',
               'reach', 'frequency', 'search']


def _starts_with(nl, kws):
    p = r'^(' + '|'.join(re.escape(k) for k in kws) + r')(?=$|[^a-z])'
    return re.match(p, nl) is not None


def classify(name: str) -> str:
    n = name.strip()
    nl = n.lower()
    if n.startswith('%') or re.match(
            r'^(rain|clouds|temperature|weather|average temperature)\b', nl):
        return "F. Autres"
    if _starts_with(nl, COST_KWS):
        return "A. Coûts"
    if re.search(r'\bperformances?\b', nl):
        return "E. Performances"
    if re.match(r'^kpi[s]? (evolution|par|by) ', nl) or re.match(r'^kpis?\b', nl):
        return "E. Performances"
    if re.match(r'^active clients', nl) or re.match(r'^account metric', nl):
        return "E. Performances"
    if re.match(r'^(meta - )?top ads', nl):
        return "E. Performances"
    if re.search(r'\bconv(ersion)?[s_ ]+value', nl):
        return "C. Revenu"
    if re.search(r'\bbasket\b', nl) or re.match(r'^(average|avg)[\s.]', nl):
        return "C. Revenu"
    if _starts_with(nl, REVENUE_KWS):
        return "C. Revenu"
    if _starts_with(nl, CONV_KWS):
        return "B. Conversions"
    if _starts_with(nl, TRAFFIC_KWS):
        return "D. Trafic"
    return "F. Autres"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    mb = connect()

    # 1. Snapshot pré-vol
    print(f"=== Snapshot du sous-arbre Cross-platform ({XPLAT_ID})... ===")
    baseline = capture_state(mb.get, root_id=XPLAT_ID)
    MIGRATION_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    snap_path = MIGRATION_DIR / f"xplat-snapshot-{ts}.json"
    snap_path.write_text(json.dumps(baseline.to_dict(), indent=2, ensure_ascii=False))
    print(f"  {len(baseline.collections)} collections, {len(baseline.cards)} cartes")
    print(f"  Snapshot baseline : {snap_path}")

    # 2. Classification + plan
    plan = {fam[0]: [] for fam in FAMILIES}
    for cid, card in baseline.cards.items():
        fam = classify(card.name)
        plan[fam].append(cid)
    print(f"\n=== Plan ({sum(len(v) for v in plan.values())} cartes à déplacer) ===")
    for fam, _ in FAMILIES:
        print(f"  {fam} : {len(plan[fam])} cartes")

    if not args.yes:
        if input("\nLancer la migration ? [tape 'oui'] ").strip() != "oui":
            sys.exit("Annulé.")

    # 3. Création des 6 collections-familles sous 214
    print(f"\n=== Création des 6 collections sous Cross-platform ({XPLAT_ID})... ===")
    family_ids = {}
    for name, desc in FAMILIES:
        res = mb.create_collection(
            collection_name=name,
            parent_collection_id=XPLAT_ID,
            return_results=True,
        )
        if not res:
            sys.exit(f"Échec création de la collection {name!r}")
        family_ids[name] = res["id"]
        # Description posée séparément
        _check(mb.put(f"/api/collection/{res['id']}", json={"description": desc}),
               f"description {name!r}")
        print(f"  créée : {name} -> id {res['id']}")

    # 4. Déplacement des cartes
    print(f"\n=== Déplacement des cartes... ===")
    moved = 0
    for fam, cids in plan.items():
        dest = family_ids[fam]
        for cid in cids:
            _check(mb.put(f"/api/card/{cid}", json={"collection_id": dest}),
                   f"déplacement carte {cid}")
            moved += 1
            if moved % 50 == 0:
                print(f"  ... {moved} cartes déplacées")
    print(f"  Total déplacé : {moved} cartes")

    # 5. Archivage des sous-collections d'entité devenues vides
    # On itère par profondeur croissante : la sub-sub-coll la plus profonde d'abord.
    print(f"\n=== Archivage des collections d'entité vides... ===")
    # Toutes les collections présentes dans le snapshot, triées par profondeur (parent en remontant)
    # Approche : itérer plusieurs passes, à chaque passe archive les collections vides.
    archived_ids = set()
    for _ in range(5):
        # Refresh items count for each non-archived collection in the baseline subtree
        any_archived = False
        for coll_id, coll in list(baseline.collections.items()):
            if coll_id in archived_ids or coll_id == XPLAT_ID:
                continue
            if coll_id in family_ids.values():
                continue
            resp = mb.get(f"/api/collection/{coll_id}/items?limit=10")
            if resp is False:
                print(f"  WARNING : lecture collection {coll_id} échouée — ignorée")
                continue
            items = resp.get("data", [])
            if not items:
                _check(mb.put(f"/api/collection/{coll_id}",
                              json={"archived": True}),
                       f"archivage collection {coll_id}")
                print(f"  archivée : {coll_id} «{coll.name}»")
                archived_ids.add(coll_id)
                any_archived = True
        if not any_archived:
            break

    # 6. Vérification d'invariant
    print(f"\n=== Vérification d'invariant... ===")
    current = capture_state(mb.get, root_id=XPLAT_ID)
    divergences = verify_invariant(baseline, current)
    if divergences:
        print("DIVERGENCES DÉTECTÉES :")
        for d in divergences:
            print(f"  [{d.kind}] carte {d.card_id} : {d.detail}")
        sys.exit(1)
    print(f"OK — {len(current.cards)} cartes intactes (hors déplacement), "
          f"0 divergence.")
    print(f"\nSnapshot baseline pour rollback : {snap_path}")


if __name__ == "__main__":
    main()
