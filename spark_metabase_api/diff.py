"""Différentiel avant/après d'une écriture Metabase.

C'est la brique que rien ne remplace : ni l'API EE, ni les 139 commandes du
CLI `mb` (aucun verbe diff/compare/baseline), et Metabase documente lui-même
ne pas savoir détecter un changement de logique de calcul comme cassant.

Deux modes :
  identical -- un écart est une ERREUR (un refacto doit préserver les nombres)
  monitor   -- un écart est un AVERTISSEMENT (une migration les change exprès)

Ce module ne fait aucun appel réseau : on lui passe deux jeux de résultats déjà
lus. C'est ce qui le rend testable hors-ligne et sûr à appeler avant un apply.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Finding:
    target: str
    check: str
    level: str  # "error" | "warn" | "ok"
    message: str
    before: Any = None
    after: Any = None


@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)

    def add(self, f: Finding) -> None:
        self.findings.append(f)

    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.level == "error"]

    def ok(self) -> bool:
        return not self.errors()

    def summary(self) -> str:
        counts: Dict[str, int] = {}
        for f in self.findings:
            counts[f.level] = counts.get(f.level, 0) + 1
        parts = ["{} {}".format(v, k) for k, v in sorted(counts.items())]
        return ", ".join(parts) or "no findings"

    def render(self) -> str:
        glyph = {"error": "✗", "warn": "!", "ok": "✓"}
        lines = ["  {}  {:<12} {}  [{}]".format(
            glyph.get(f.level, "?"), f.check, f.target, f.message)
            for f in self.findings]
        return "\n".join(lines) + ("\n" if lines else "") + "Report: " + self.summary()

    def exit_code(self) -> int:
        return 1 if self.errors() else 0


class ValidationError(Exception):
    def __init__(self, report: "Report"):
        self.report = report
        super().__init__("validation failed:\n" + report.render())


def _signature(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Empreinte d'un jeu de lignes : nombre de lignes, colonnes, sommes des
    colonnes numériques. Une colonne n'est numérique que si toutes ses valeurs
    non nulles sont int/float et pas bool."""
    cols = list(rows[0].keys()) if rows else []
    sums: Dict[str, float] = {}
    for c in cols:
        vals = [r.get(c) for r in rows if r.get(c) is not None]
        if vals and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
            sums[c] = sum(vals)
    return {"row_count": len(rows), "columns": cols, "sums": sums}


def check_differential(target, before, after, mode="monitor", tolerance=0.0) -> List[Finding]:
    """Compare deux jeux de résultats tabulaires (avant/après).

    tolerance : seuil fractionnaire sur les sommes numériques (écart/denom > tolerance)."""
    sb, sa = _signature(before), _signature(after)
    level = "error" if mode == "identical" else "warn"
    findings: List[Finding] = []

    if sb["row_count"] != sa["row_count"]:
        findings.append(Finding(target, "differential", level,
            "row count {} -> {}".format(sb["row_count"], sa["row_count"]),
            before=sb["row_count"], after=sa["row_count"]))

    if set(sb["columns"]) != set(sa["columns"]):
        findings.append(Finding(target, "differential", level, "columns changed",
            before=sb["columns"], after=sa["columns"]))

    after_cols = set(sa["columns"])
    for c, bsum in sb["sums"].items():
        asum = sa["sums"].get(c)
        if asum is None:
            # La colonne était numérique avant et n'a plus de somme numérique. Si
            # elle est toujours présente sous le même nom, elle a régressé en
            # tout-NULL ou en type non numérique : un écart réel que ni le compte
            # de lignes ni l'ensemble des colonnes ne peuvent voir.
            if c in after_cols:
                findings.append(Finding(target, "differential", level,
                    "sum({}) numeric -> non-numeric/all-null".format(c),
                    before=bsum, after=None))
            continue
        denom = abs(bsum) or 1.0
        delta = abs(asum - bsum)
        if delta != delta or delta / denom > tolerance:  # NaN, ou au-delà de la tolérance
            findings.append(Finding(target, "differential", level,
                "sum({}) {} -> {}".format(c, bsum, asum), before=bsum, after=asum))

    if not findings:
        findings.append(Finding(target, "differential", "ok", "no significant change"))

    return findings


def check_values(target, before, after, mode="monitor", tolerance=0.0) -> List[Finding]:
    """Compare deux séquences de valeurs scalaires (la convention multiset
    numérique trié/arrondi de la migration conv).

    tolerance=0.0 reproduit exactement un `before != after`."""
    level = "error" if mode == "identical" else "warn"
    b, a = list(before or []), list(after or [])
    if len(b) != len(a):
        return [Finding(target, "values", level,
            "value count {} -> {}".format(len(b), len(a)), before=len(b), after=len(a))]
    is_num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    if all(is_num(x) for x in b) and all(is_num(x) for x in a):
        diffs, first = 0, None
        for x, y in zip(sorted(b), sorted(a)):
            denom = abs(x) or 1.0
            d = abs(y - x)
            if d != d or d / denom > tolerance:  # NaN ou au-delà de la tolérance
                diffs += 1
                if first is None:
                    first = (x, y)
        if diffs:
            return [Finding(target, "values", level,
                "{}/{} values differ beyond tolerance, first {} -> {}".format(
                    diffs, len(b), first[0], first[1]),
                before=first[0], after=first[1])]
    elif b != a:
        return [Finding(target, "values", level, "values differ (non-numeric)",
                        before=b, after=a)]
    return [Finding(target, "values", "ok", "{} values, no change".format(len(b)))]
