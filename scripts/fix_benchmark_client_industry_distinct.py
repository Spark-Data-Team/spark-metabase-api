"""Corrige les tableaux « Performance (client vs industry) (benchmark) » 56568 / 56569.

Leur CTE client_industry rend une ligne par client et non par industrie : la
jointure sur l'industrie démultiplie alors chaque ligne par le nombre de clients
de la même industrie (×24 à ×41 sans client choisi, ×2 avec deux clients de la
même industrie). Un SELECT DISTINCT suffit ; avec un seul client, rien ne change.

    python scripts/fix_benchmark_client_industry_distinct.py            # dry-run : mesure avant / après sans écrire
    python scripts/fix_benchmark_client_industry_distinct.py --apply
    python scripts/fix_benchmark_client_industry_distinct.py --rollback migration/snapshot-card-56568-....json
"""

import argparse
import copy
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.stdout.reconfigure(encoding="utf-8")   # console Windows en cp1252 sinon

from spark_metabase_api import connect, cards, http  # noqa: E402

CARTES = [56568, 56569]
ANCIEN = "client_industry AS (\n    \n    SELECT \n        utils.client_categories.industry\n"
NOUVEAU = "client_industry AS (\n    \n    SELECT DISTINCT\n        utils.client_categories.industry\n"
DOSSIER_TRACE = os.path.join(os.path.dirname(__file__), "..", "migration")


def cible(tag):
    return ["dimension", ["template-tag", tag]]


OPENAI_60J = [{"type": "category", "target": cible("channel"), "value": ["openai"]},
              {"type": "date/all-options", "target": cible("date"), "value": "past60days"}]
# Un seul client = l'usage normal : doit rester identique. Sans client = le cas cassé.
CAS = {
    "aucun client (openai, 60 j)": (OPENAI_60J, "change"),
    "BYmyCAR seul (openai, 60 j)": (OPENAI_60J + [{"type": "category", "target": cible("clients"), "value": ["BYmyCAR"]}], "identique"),
    "Dougs seul (tous canaux, 30 j)": ([{"type": "date/all-options", "target": cible("date"), "value": "past30days"},
                                        {"type": "category", "target": cible("clients"), "value": ["Dougs"]}], "identique"),
}


def executer(mb, carte, sql, parametres):
    q = copy.deepcopy(carte["dataset_query"])
    q["native"]["query"] = sql
    r = http.post(mb, "/api/dataset", json=dict(q, parameters=parametres))
    if r.get("status") != "completed":
        raise RuntimeError("carte {} : {}".format(carte["id"], (r.get("error") or "")[:300]))
    cols = [c["name"] for c in r["data"]["cols"]]
    return sorted((row[0], round(row[cols.index("COST")], 2)) for row in r["data"]["rows"])


def mesurer(mb, carte, sql):
    return {nom: executer(mb, carte, sql, p) for nom, (p, _attendu) in CAS.items()}


def comparer(avant, apres):
    """Rend la liste des écarts à l'attendu ; vide = conforme."""
    ecarts = []
    for nom, (_p, attendu) in CAS.items():
        identique = avant[nom] == apres[nom]
        print("     {:32s} {:9s} ({} lignes)".format(nom, "identique" if identique else "changé", len(apres[nom])))
        if not identique:
            print("        avant {}".format(avant[nom][:4]))
            print("        après {}".format(apres[nom][:4]))
        if (attendu == "identique") != identique:
            ecarts.append("{} : attendu {}".format(nom, attendu))
    return ecarts


def snapshot(carte):
    os.makedirs(DOSSIER_TRACE, exist_ok=True)
    chemin = os.path.join(DOSSIER_TRACE, "snapshot-card-{}-{}.json".format(carte["id"], datetime.now().strftime("%Y%m%dT%H%M%S")))
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(carte, f, ensure_ascii=False, indent=1)
    return chemin


def rollback(mb, chemins):
    for chemin in chemins:
        with open(chemin, encoding="utf-8") as f:
            carte = json.load(f)
        cards.put_card(mb, carte["id"], {"dataset_query": carte["dataset_query"]})
        print("carte {} restaurée depuis {}".format(carte["id"], chemin))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="écrit la correction")
    ap.add_argument("--rollback", help="snapshots à restaurer, séparés par des virgules")
    args = ap.parse_args()

    mb = connect()
    if args.rollback:
        rollback(mb, args.rollback.split(","))
        return

    for cid in CARTES:
        carte = cards.get_card(mb, cid)
        sql = cards.card_sql(carte)
        if sql.count(ANCIEN) != 1:
            print("\n{} : motif absent ou multiple, carte ignorée (déjà corrigée ?)".format(cid))
            continue
        corrige = sql.replace(ANCIEN, NOUVEAU)
        print("\n== {} {}".format(cid, carte["name"]))
        avant = mesurer(mb, carte, sql)

        if not args.apply:
            ecarts = comparer(avant, mesurer(mb, carte, corrige))
            print("   " + ("conforme" if not ecarts else "NON CONFORME : " + " ; ".join(ecarts)))
            continue

        chemin = snapshot(carte)
        dq = copy.deepcopy(carte["dataset_query"])
        dq["native"]["query"] = corrige
        relu = cards.put_card(mb, cid, {"dataset_query": dq})
        ecarts = comparer(avant, mesurer(mb, relu, cards.card_sql(relu)))
        print("   snapshot : {}".format(chemin))
        if ecarts:
            rollback(mb, [chemin])
            raise RuntimeError("carte {} non conforme, restaurée : {}".format(cid, " ; ".join(ecarts)))
        print("   corrigée")

    if not args.apply:
        print("\nDry-run : rien n'a été écrit. Relancer avec --apply.")


if __name__ == "__main__":
    main()
