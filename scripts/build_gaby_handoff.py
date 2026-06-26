#!/usr/bin/env python3
"""Construit LE fichier de passation « conversions à trancher » pour le team lead :
un CSV clair et net des slots qu'on ne peut PAS migrer automatiquement parce que la
donnée Airtable est ambiguë ou manquante. Trois catégories :
  CONFLIT             : 1 slot positionnel = plusieurs conversions nommées (selon compte/event)
  INDECIS (… OR …)    : new_type non tranché (ex. « Content views OR View Item »)
  PAIRING_AMBIGU      : ligne multi-select dont type/new_type n'ont pas le même nombre de valeurs
  NON_MAPPE_UTILISE   : slot utilisé par un dashboard mais sans conversion nommée (à remplir)

Sources : l'export CSV Airtable (contexte) + le mapping résolu + conv-targets (dashboards).
Sortie : migration/CONVERSIONS-A-TRANCHER.csv
Usage : python3 scripts/build_gaby_handoff.py /chemin/Conversions.csv
"""
import csv, json, sys
from collections import defaultdict
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
import conv_lib

SLOT_TO_TYPE = {v: k for k, v in conv_lib.TYPE_TO_SLOT.items()}


def slot_col(slot):
    return "conversions" if slot == 0 else f"conversions_{slot}"


def slot_label(slot):
    return f"{SLOT_TO_TYPE.get(slot, '?')} ({slot_col(slot)})"


def main():
    csv_path = Path(sys.argv[1])
    # 1) contexte par (client, slot) depuis le CSV : valeurs nommées vues + plateformes/comptes/events
    ctx = defaultdict(lambda: defaultdict(list))   # client -> slot -> [(new_type, platform, account, event)]
    ambiguous_pairs = []                            # lignes multi-select non pairables
    or_values = []                                  # new_type « … OR … »
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            client = (row.get("brand_name") or "").strip()
            if not client:
                continue
            platform = (row.get("platform_name") or "").strip()
            account = (row.get("account_name") or "").strip()
            event = (row.get("conversion_name") or row.get("name") or "").strip()
            pairs, amb = conv_lib.split_multiselect_pairs(row.get("type"), row.get("new_type"))
            if amb:
                ambiguous_pairs.append((client, row.get("type"), row.get("new_type"), platform, account, event))
            for t, nt in pairs:
                slot = conv_lib.TYPE_TO_SLOT.get(t)
                if slot is None:
                    continue
                ctx[client][slot].append((nt, platform, account, event))
                if nt and " OR " in nt:
                    or_values.append((client, slot, nt, platform, account, event))

    mapping = json.loads((REPO / "migration" / "conv-client-mapping.json").read_text())

    # 2) quels slots chaque client utilise réellement (dashboards) -> priorisation
    used = defaultdict(lambda: defaultdict(set))    # client -> slot -> {dashboard names}
    tgts = json.loads((REPO / "migration" / "conv-targets.json").read_text())
    for d in tgts:
        cl = d.get("client")
        for tile in d.get("tiles", []):
            for col in tile.get("old_cols", []):
                s = conv_lib._slot_of(col)
                if s is not None:
                    used[cl][s].add(d.get("dashboard_name", ""))

    def dashes(client, slot):
        names = sorted(used.get(client, {}).get(slot, []))
        return f"{len(names)} dash" + (f" : {', '.join(n[:30] for n in names[:3])}" + ("…" if len(names) > 3 else "") if names else "")

    rows_out = []
    seen = set()

    def add(client, issue, slot_txt, value, context, dash, action):
        key = (client, issue, slot_txt, value)
        if key in seen:
            return
        seen.add(key)
        rows_out.append({"client": client, "type_probleme": issue, "slot": slot_txt,
                         "valeur_actuelle": value, "contexte": context,
                         "dashboards_concernes": dash, "a_trancher": action})

    # CONFLIT : slot mappé à plusieurs new_types
    for client, slots in mapping.items():
        for s, v in slots.items():
            s = int(s)
            if v == conv_lib.CONFLICT:
                vals = ctx.get(client, {}).get(s, [])
                distinct = sorted({nt for nt, *_ in vals if nt})
                detail = " ; ".join(f"{nt} [{p}/{a or '?'}{('/'+e) if e else ''}]" for nt, p, a, e in vals if nt)
                add(client, "CONFLIT", slot_label(s), " ou ".join(distinct), detail[:300],
                    dashes(client, s), "Quelle conversion nommée pour ce slot ?")
            elif v == conv_lib.UNMAPPED and used.get(client, {}).get(s):
                add(client, "NON_MAPPE_UTILISE", slot_label(s), "(vide)", "",
                    dashes(client, s), "Renseigner la conversion nommée (slot utilisé par un dashboard).")

    # INDECIS (… OR …)
    for client, s, nt, p, a, e in or_values:
        add(client, "INDECIS (… OR …)", slot_label(s), nt, f"{p}/{a or '?'}{('/'+e) if e else ''}",
            dashes(client, s), "Trancher entre les options du « OR ».")

    # PAIRING_AMBIGU (multi-select cardinalités ≠)
    for client, tc, ntc, p, a, e in ambiguous_pairs:
        add(client, "PAIRING_AMBIGU", str(tc), str(ntc), f"{p}/{a or '?'}{('/'+e) if e else ''}",
            "", "Préciser quel type positionnel ↔ quelle conversion nommée.")

    rows_out.sort(key=lambda r: (r["type_probleme"], r["client"], r["slot"]))
    out = REPO / "migration" / "CONVERSIONS-A-TRANCHER.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["client", "type_probleme", "slot", "valeur_actuelle",
                                           "contexte", "dashboards_concernes", "a_trancher"])
        w.writeheader()
        w.writerows(rows_out)

    from collections import Counter
    by = Counter(r["type_probleme"] for r in rows_out)
    nclients = len({r["client"] for r in rows_out})
    print(f"{len(rows_out)} lignes à trancher | {nclients} clients concernés")
    for k, v in by.most_common():
        print(f"  {k:22} {v}")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
