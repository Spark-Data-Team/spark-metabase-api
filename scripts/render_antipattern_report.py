#!/usr/bin/env python3
"""Synthèse finale de l'audit 2 anti-patterns SQL : digest md + JSON exhaustif.

Reclasse B de façon déterministe (backslash simple = BUG, backslash double = OK,
prouvé empiriquement sur Snowflake) ; conserve les verdicts A (vérif 3 lentilles).
"""
from __future__ import annotations

import glob
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIG = ROOT / "migration"
DOCS = ROOT / "docs" / "audits"

META = re.compile(r"(\\+)([.?+(){}\[\]|^$*])")              # runs de backslash avant un méta-char
SINGLE_FIX = re.compile(r"(?<!\\)\\([.?+(){}\[\]|^$*])")    # backslash simple -> [char]
# littéraux de pattern dans un REGEXP_* (1er ou 2e argument string)
LITERAL = re.compile(r"'((?:[^'\\]|\\.)*)'")


def escape_profile(sql: str):
    single, double = set(), set()
    for m in META.finditer(sql):
        (single if len(m.group(1)) % 2 else double).add(m.group(2))
    return single, double


def b_fixes(sql: str):
    """Retourne [(find, replace)] pour chaque littéral contenant un backslash simple+méta."""
    out, seen = [], set()
    # cible les littéraux situés dans un appel REGEXP_*
    for call in re.finditer(r"(REGEXP_REPLACE|REGEXP_LIKE|REGEXP_SUBSTR|REGEXP_COUNT|RLIKE)\s*\(", sql, re.I):
        seg = sql[call.start():call.start() + 600]
        for lit in LITERAL.finditer(seg):
            pat = lit.group(1)
            s, _ = escape_profile(pat)
            if s and pat not in seen:
                seen.add(pat)
                fixed = SINGLE_FIX.sub(r"[\1]", pat)
                out.append((f"'{pat}'", f"'{fixed}'"))
    return out


def load():
    res = json.load(open(MIG / "antipattern-audit-results.json"))["results"]
    cand = json.load(open(sorted(glob.glob(str(MIG / "sql-antipattern-candidates-*.json")))[-1]))
    emp = json.load(open(MIG / "antipattern-empirical.json"))
    by_id = {}
    for k in ("a_candidates", "b_candidates"):
        for c in cand[k]:
            by_id.setdefault(c["id"], c)  # garde la 1re (a_candidates en priorité ok)
    sql = {c["id"]: c["sql"] for k in ("a_candidates", "b_candidates") for c in cand[k]}
    nm = {c["id"]: c["name"] for k in ("a_candidates", "b_candidates") for c in cand[k]}
    dash = {c["id"]: (c.get("dashboards") or []) for k in ("a_candidates", "b_candidates") for c in cand[k]}
    return res, sql, nm, dash, emp


def reclassify(res, sql):
    """Ajoute corrected/severity/fixes à chaque résultat."""
    for r in res:
        a = r.get("analysis") or {}
        cid = r["card_id"]
        if r["antipattern"] == "A":
            r["corrected"] = r.get("final_verdict", "ERROR")
            r["severity"] = "haute" if r["corrected"] == "BUG" else ("à trancher" if r["corrected"] == "REVIEW" else "—")
            r["fixes"] = [(a["fix_find"], a["fix_replace"])] if r["corrected"] == "BUG" and a.get("fix_find") else []
        else:  # B — règle déterministe
            single, double = escape_profile(sql.get(cid, ""))
            if single:
                r["corrected"] = "BUG"
                r["fixes"] = b_fixes(sql.get(cid, ""))
                # gravité : la colonne fautive est-elle réellement consommée ?
                txt = sql.get(cid, "")
                alias_used = bool(re.search(r"AS\s+client_domain", txt, re.I)) and txt.lower().count("client_domain") > 1
                alias_used = alias_used or (re.search(r"AS\s+domain\b", txt, re.I) and txt.lower().count(" domain") > 2)
                if cid == 14908:
                    r["severity"] = "haute (domaine affiché, 17 dashboards)"
                elif single == {"|"}:
                    r["severity"] = "interne (cartes d'audit, 0 dashboard)"
                elif alias_used:
                    r["severity"] = "moyenne (colonne domaine consommée)"
                else:
                    r["severity"] = "latente (regex faux mais colonne non affichée)"
            else:
                r["corrected"] = "OK"
                r["severity"] = "—"
                r["fixes"] = []
                r["ok_reason"] = "backslash double = échappement correct (vérifié empiriquement)"
    return res


def fmt_dash(dl, n):
    if not dl:
        return "0 dashboard"
    names = [f'{d["name"]}(#{d["id"]})' for d in dl[:n]]
    return "; ".join(names) + (f" +{len(dl)-n}" if len(dl) > n else "")


def main():
    res, sql, nm, dash, emp = load()
    res = reclassify(res, sql)
    date = datetime.now().strftime("%Y-%m-%d")

    buckets = {"BUG": [], "REVIEW": [], "OK": [], "ERROR": []}
    for r in res:
        buckets[r["corrected"]].append(r)

    def sk(r):
        sev_order = {"haute": 0, "haute (domaine affiché, 17 dashboards)": 0, "moyenne (colonne domaine consommée)": 1,
                     "latente (regex faux mais colonne non affichée)": 2, "interne (cartes d'audit, 0 dashboard)": 3}
        return (0 if r["antipattern"] == "A" else 1, sev_order.get(r.get("severity"), 5), r["card_id"])

    # ---------- JSON exhaustif ----------
    full = {"generated": date, "empirical": emp,
            "counts": {k: len(v) for k, v in buckets.items()},
            "results": res}
    full_path = MIG / f"antipattern-audit-full-{date}.json"
    full_path.write_text(json.dumps(full, indent=2, ensure_ascii=False))

    # ---------- digest md ----------
    L = []
    L.append(f"# Audit anti-patterns SQL Metabase — {date}\n")
    L.append("Lecture seule, **aucune carte modifiée**. Scan de toutes les questions natives de "
             "l'instance pour deux anti-patterns, puis vérification adversariale et confirmation "
             "empirique sur Snowflake.\n")
    L.append("- **A** — JOIN sur `kp__keyword_*` sans `language`/`zone` → produit cartésien (volumes gonflés, clients multi-zones).")
    L.append("- **B** — backslash simple `\\.` devant un méta-char dans un REGEXP Snowflake → l'échappement est mangé.\n")

    er = emp["regex_escape_proof"]
    L.append("## Méthode & preuves empiriques (Snowflake, lecture seule)\n")
    zones = ", ".join(dict.fromkeys(z["zone"] for z in emp["zones"]))
    L.append(f"**A — inflation mesurée** · client `{emp['client']}` (multi-zones : {zones}), "
             f"mois {emp['month']} :")
    L.append(f"join bogué (keyword seul) = **{emp['buggy_join_keyword_only']:,}** vs corrigé "
             f"(keyword+language+zone) = **{emp['fixed_join_keyword_language_zone']:,}** → "
             f"**×{emp['inflation_factor']:.2f} (+{emp['inflation_pct']:.0f} %)**. "
             f"Grain kp = 1 ligne/(keyword,language,zone,mois) → le fix language+zone est complet.\n")
    L.append(f"**B — {er['instance_rule']}** Tests :\n")
    L.append("| pattern SQL | entrée | résultat | verdict |")
    L.append("|---|---|---|---|")
    for t in er["tests"]:
        L.append(f'| `{t["sql_pattern"]}` | `{t["input"]}` | `{t["result"]}` | {t["verdict"]} |')
    L.append("\n→ Conséquence : un backslash **simple** est un vrai bug ; un backslash **double** "
             "(`\\\\.`) ou une classe `[.]` sont corrects. La reclassification B ci-dessous est "
             "déterministe sur ce critère.\n")

    L.append("## Compte\n")
    L.append(f"- **{len(res)}** cartes analysées (5 367 scannées, 5 068 natives, 100 % SQL extrait).")
    L.append(f"- **{len(buckets['BUG'])} BUG** à corriger · **{len(buckets['REVIEW'])} REVIEW** à trancher · "
             f"**{len(buckets['OK'])} OK**.")
    nb_a_bug = sum(1 for r in buckets['BUG'] if r['antipattern'] == 'A')
    nb_b_bug = len(buckets['BUG']) - nb_a_bug
    L.append(f"  - BUG : {nb_a_bug} en A (cartésien), {nb_b_bug} en B (regex).")
    L.append("- 226 cartes avec REGEXP sans backslash suspect : écartées (probable OK), non analysées une à une.\n")

    # ---- A bugs ----
    L.append("## A — BUG cartésien (correctif : ajouter language + zone à l'ON)\n")
    for r in sorted([x for x in buckets["BUG"] if x["antipattern"] == "A"], key=sk):
        a = r["analysis"]
        L.append(f'### #{r["card_id"]} — {nm[r["card_id"]]}')
        L.append(f'Dashboards : {fmt_dash(dash[r["card_id"]], 6)}')
        if a.get("inflation_note"):
            L.append(f'Impact : {a["inflation_note"][:280]}')
        for find, repl in r["fixes"]:
            L.append("\n**Find :**\n```sql\n" + (find or "").strip() + "\n```")
            L.append("**Replace :**\n```sql\n" + (repl or "").strip() + "\n```")
        L.append("")

    # ---- B bugs ----
    L.append("## B — BUG regex (backslash simple mangé)\n")
    for r in sorted([x for x in buckets["BUG"] if x["antipattern"] == "B"], key=sk):
        L.append(f'### #{r["card_id"]} — {nm[r["card_id"]]}  _(gravité : {r["severity"]})_')
        L.append(f'Dashboards : {fmt_dash(dash[r["card_id"]], 6)}')
        for find, repl in r["fixes"]:
            L.append("\n**Find :**\n```\n" + find + "\n```")
            L.append("**Replace :**\n```\n" + repl + "\n```")
        L.append("")

    # ---- REVIEW ----
    L.append("## REVIEW — à trancher\n")
    for r in sorted(buckets["REVIEW"], key=sk):
        a = r.get("analysis") or {}
        q = a.get("review_question") or (a.get("reasoning") or "")[:200]
        L.append(f'- **#{r["card_id"]}** {nm[r["card_id"]]} ({r["antipattern"]}) — {q}')
    L.append("")

    # ---- OK (B double-backslash) compacted ----
    okb = [r for r in buckets["OK"] if r["antipattern"] == "B"]
    if okb:
        L.append("## OK confirmés — B backslash double (aucune action)\n")
        L.append(", ".join(f'#{r["card_id"]}' for r in sorted(okb, key=lambda r: r["card_id"])))
        L.append("")

    L.append(f"\n_Détail complet (extraits, raisonnements, votes de vérification) : "
             f"`{full_path.relative_to(ROOT)}`_")

    DOCS.mkdir(parents=True, exist_ok=True)
    md_path = DOCS / f"sql-antipatterns-{date}.md"
    md_path.write_text("\n".join(L))
    print("Digest :", md_path)
    print("Détail :", full_path)
    print(f"BUG={len(buckets['BUG'])} (A={nb_a_bug} B={nb_b_bug}) "
          f"REVIEW={len(buckets['REVIEW'])} OK={len(buckets['OK'])}")


if __name__ == "__main__":
    main()
