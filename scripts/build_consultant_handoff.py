#!/usr/bin/env python3
"""Transforme le CSV brut « conversions à trancher » (CONVERSIONS-A-TRANCHER.csv, issu de
build_gaby_handoff.py) en un handoff CONSULTANT *mâché* : 1 question en clair + options à cocher
par décision, trié par impact (nb dashboards), avec une colonne RÉPONSE vide à remplir.

But (user 2026-06-29) : le consultant ne doit RIEN avoir à comprendre — juste lire la question, cocher
une option, renvoyer. Round-trip fluide : on génère -> il remplit la colonne RÉPONSE -> on re-parse
(parse_consultant_answers.py) -> on débloque les dashboards.

Filtrage : si --blockers migration/residual-blockers.json est fourni (set de [client, slot] qui ont
RÉELLEMENT laissé un dashboard sur l'ancien dans le sweep), on ne garde QUE ces décisions (sinon tout).
-> handoff court et 100% actionnable.

Usage :
  python3 scripts/build_consultant_handoff.py [migration/CONVERSIONS-A-TRANCHER.csv] [--blockers <json>]
Sortie : migration/HANDOFF-consultants.csv  +  migration/HANDOFF-consultants-LISEZMOI.md
"""
import sys, csv, json, re
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "migration" / "CONVERSIONS-A-TRANCHER.csv"
OUT = REPO / "migration" / "HANDOFF-consultants.csv"


def _slot_num(slot):
    m = re.search(r"\((conversions?)_?(\d*)\)", slot)
    return int(m.group(2)) if (m and m.group(2)) else 0


def _position_label(slot):
    n = _slot_num(slot)
    if "Main" in slot or n == 0:
        return "la conversion PRINCIPALE"
    ord_fr = {1: "1ʳᵉ", 2: "2ᵉ", 3: "3ᵉ"}.get(n, f"{n}ᵉ")
    return f"la {ord_fr} conversion (position {n})"


def _options(typ, valeur):
    """Liste d'options à cocher depuis la valeur brute."""
    if typ == "CONFLIT":
        return [v.strip() for v in re.split(r"\s+ou\s+|,", valeur) if v.strip()]
    if typ.startswith("INDECIS"):
        return [v.strip() for v in re.split(r"\s+OR\s+", valeur) if v.strip()]
    return []  # NON_MAPPE_UTILISE / PAIRING : pas d'options fermées -> réponse libre guidée


def _question(typ, slot, ctx):
    pos = _position_label(slot)
    if typ == "CONFLIT":
        return f"Pour {pos}, plusieurs conversions nommées sont possibles selon le compte. Laquelle est la bonne ?"
    if typ.startswith("INDECIS"):
        return f"Pour {pos}, la valeur saisie est un choix non tranché. Laquelle retenir ?"
    if typ == "NON_MAPPE_UTILISE":
        return f"{pos.capitalize()} est utilisée dans des dashboards mais n'a pas de conversion nommée. Laquelle est-ce ?"
    if typ == "PAIRING_AMBIGU":
        return f"L'ordre des conversions est ambigu ici. Précise quelle conversion nommée correspond à {pos}."
    return f"À préciser pour {pos}."


def _ndash(s):
    m = re.match(r"\s*(\d+)\s+dash", s or "")
    return int(m.group(1)) if m else 0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    src = Path(args[0]) if args else SRC
    blockers = None
    if "--blockers" in sys.argv:
        bf = sys.argv[sys.argv.index("--blockers") + 1]
        data = json.loads(Path(bf).read_text())
        blockers = {(b["client"], int(b["slot"])) for b in data}  # set (client, slot_num)

    rows = list(csv.DictReader(open(src, encoding="utf-8-sig")))
    out = []
    for r in rows:
        if blockers is not None and (r["client"], _slot_num(r["slot"])) not in blockers:
            continue
        opts = _options(r["type_probleme"], r["valeur_actuelle"])
        out.append({
            "priorité (nb dashboards)": _ndash(r["dashboards_concernes"]),
            "client": r["client"],
            "QUESTION": _question(r["type_probleme"], r["slot"], r["contexte"]),
            "option 1": opts[0] if len(opts) > 0 else "",
            "option 2": opts[1] if len(opts) > 1 else "",
            "option 3": opts[2] if len(opts) > 2 else "",
            "contexte (pour aider)": r["contexte"][:200],
            "dashboards concernés": r["dashboards_concernes"],
            "✍️ TA RÉPONSE": "",
            "ref": f"{r['client']}§{_slot_num(r['slot'])}§{r['type_probleme']}",  # machine (ne pas toucher)
        })
    # tri : par client puis impact décroissant
    out.sort(key=lambda x: (x["client"], -x["priorité (nb dashboards)"]))
    cols = ["priorité (nb dashboards)", "client", "QUESTION", "option 1", "option 2", "option 3",
            "contexte (pour aider)", "dashboards concernés", "✍️ TA RÉPONSE", "ref"]
    with OUT.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(out)
    nclients = len({x["client"] for x in out})
    print(f"écrit {OUT} : {len(out)} décisions / {nclients} clients" +
          (f" (filtré aux {len(blockers)} blockers réels)" if blockers is not None else " (TOUT, non filtré)"))


if __name__ == "__main__":
    main()
