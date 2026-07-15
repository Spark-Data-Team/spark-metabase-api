"""Corrige la priorité 'dashboards concernés' des handoffs conversions pour ne compter que
les dashboards où le slot est RÉELLEMENT montré (visible ou plausiblement visible), en
excluant les tuiles qui le masquent (override-aware). Source : conv-visibility-by-slot.json.

- Patche migration/CONVERSIONS-A-TRANCHER.csv (colonne dashboards_concernes).
- Régénère migration/HANDOFF-consultants.csv via build_consultant_handoff.py (priorité re-dérivée).
Backups .PRE-VIS.csv écrits avant modification.
"""
import csv, json, re, subprocess, sys, shutil
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
MIG = REPO / "migration"

vis = {(r["client"], r["slot"]): r for r in json.loads((MIG / "conv-visibility-by-slot.json").read_text())}


def slot_num(slot_label):
    m = re.search(r"\((conversions?)_?(\d*)\)", slot_label)
    return int(m.group(2)) if (m and m.group(2)) else (0 if m else None)


def dashes(names):
    names = sorted(names)
    if not names:
        return "0 dash"
    head = ", ".join(n[:30] for n in names[:3])
    return f"{len(names)} dash : {head}" + ("…" if len(names) > 3 else "")


src = MIG / "CONVERSIONS-A-TRANCHER.csv"
shutil.copy(src, MIG / "CONVERSIONS-A-TRANCHER.PRE-VIS.csv")
rows = list(csv.DictReader(open(src, encoding="utf-8-sig")))
patched = dropped = 0
for r in rows:
    s = slot_num(r["slot"])
    if s is None:
        continue  # PAIRING_AMBIGU etc. — pas de slot
    v = vis.get((r["client"], s))
    if not v:
        continue
    new = dashes(v.get("shown_dash_names", []))
    if new != r["dashboards_concernes"]:
        patched += 1
    r["dashboards_concernes"] = new
    if v.get("shown_dashboards", 0) == 0:
        dropped += 1

with open(src, "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.DictWriter(fh, fieldnames=["client", "type_probleme", "slot", "valeur_actuelle",
                                       "contexte", "dashboards_concernes", "a_trancher"])
    w.writeheader(); w.writerows(rows)
print(f"à-trancher : {patched} lignes re-priorisées ; {dropped} slots à shown=0 (masqués partout)")

# regénère le handoff consultant filtré
shutil.copy(MIG / "HANDOFF-consultants.csv", MIG / "HANDOFF-consultants.PRE-VIS.csv")
subprocess.run([sys.executable, str(REPO / "scripts" / "build_consultant_handoff.py"),
                str(src), "--blockers", str(MIG / "residual-blockers-REAL.json")], check=True)
