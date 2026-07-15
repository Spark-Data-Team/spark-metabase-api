"""Régénère les handoffs conversions en définition STRICTE de visibilité :
un dashboard ne compte pour un slot QUE si une colonne de ce slot est explicitement
affichée (enabled=true, override-aware) — 'absent de la liste' = NON affiché (vérifié à
la main par l'user sur 900.care). Les slots affichés sur 0 dashboard = FAUX POSITIFS,
retirés du handoff consultant.

Source de vérité : migration/conv-visibility-by-slot.json (champ visible_dashboards / visible_dash_names).
Backups .PRE-STRICT.csv. Ne touche pas aux .PRE-VIS.csv (originaux bruts).
"""
import csv, json, re, subprocess, sys, shutil
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
MIG = REPO / "migration"

vis = {(r["client"], r["slot"]): r for r in json.loads((MIG / "conv-visibility-by-slot.json").read_text())}


def slot_num(label):
    m = re.search(r"\((conversions?)_?(\d*)\)", label)
    return (int(m.group(2)) if m.group(2) else 0) if m else None


def dashes(names):
    names = sorted(names)
    if not names:
        return "0 dash"
    return f"{len(names)} dash : " + ", ".join(n[:30] for n in names[:3]) + ("…" if len(names) > 3 else "")


def visible_names(client, slot):
    v = vis.get((client, slot))
    return v.get("visible_dash_names", []) if v else []


# 1) à-trancher : dashboards_concernes = visibles uniquement (référence complète, on garde tout)
src = MIG / "CONVERSIONS-A-TRANCHER.csv"
shutil.copy(src, MIG / "CONVERSIONS-A-TRANCHER.PRE-STRICT.csv")
rows = list(csv.DictReader(open(src, encoding="utf-8-sig")))
for r in rows:
    s = slot_num(r["slot"])
    if s is None:
        continue
    r["dashboards_concernes"] = dashes(visible_names(r["client"], s))
with open(src, "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.DictWriter(fh, fieldnames=["client", "type_probleme", "slot", "valeur_actuelle",
                                       "contexte", "dashboards_concernes", "a_trancher"])
    w.writeheader(); w.writerows(rows)

# 2) régénère le handoff consultant depuis l'à-trancher patché
subprocess.run([sys.executable, str(REPO / "scripts" / "build_consultant_handoff.py"),
                str(src), "--blockers", str(MIG / "residual-blockers-REAL.json")],
               check=True, capture_output=True)

# 3) filtre STRICT : on retire les décisions affichées sur 0 dashboard (faux positifs)
hc = MIG / "HANDOFF-consultants.csv"
shutil.copy(hc, MIG / "HANDOFF-consultants.PRE-STRICT.csv")
crows = list(csv.DictReader(open(hc, encoding="utf-8-sig")))
kept, removed = [], []
for r in crows:
    p = r["ref"].split("§")
    if "PAIRING" in r["ref"]:
        kept.append(r); continue
    client, slot = p[0], int(p[1])
    v = vis.get((client, slot), {})
    if v.get("visible_dashboards", 0) > 0:
        kept.append(r)
    else:
        removed.append((client, slot, p[2]))
cols = list(crows[0].keys())
with hc.open("w", newline="", encoding="utf-8-sig") as fh:
    w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(kept)

nclients = len({r["client"] for r in kept})
print(f"HANDOFF consultant STRICT : {len(kept)} lignes / {nclients} clients")
print(f"Retiré (faux positifs, affichés 0 dashboard) : {len({(c,s) for c,s,_ in removed})} slots")
for c, s, k in sorted(set(removed)):
    print(f"   - {c} slot {s} ({k})")
