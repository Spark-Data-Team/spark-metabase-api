"""Fusion de cartes jumelles Metabase (SQL natif) : générique + custom -> « toutes conversions ».

Contexte
--------
Chaque paire jumelle (ex. 41347 générique / 41348 custom) partage EXACTEMENT le même
échafaudage SQL (CTEs de dates, fenêtres de comparaison, FROM/JOIN/WHERE/GROUP BY,
SELECT final) ; seuls diffèrent les blocs de colonnes-métriques par conversion
(13 conversions standard côté générique, CUSTOM_CONVERSIONS_1..15 côté custom).

Méthode (merge_sqls)
--------------------
1. difflib.SequenceMatcher sur les LIGNES des deux SQL (autojunk=False, déterministe).
2. Hunks 'equal'  -> gardés tels quels (l'échafaudage commun).
3. Hunks non-equal -> union des items de liste SELECT : items du côté générique PUIS
   items du côté custom, en dédupliquant les items textuellement identiques
   (ex. préfixe partagé « impressions, clicks, cost, » dans une même ligne) et en
   réparant les virgules de jonction. Le découpage en items se fait aux virgules de
   profondeur 0 (scanner conscient des parenthèses, chaînes '...', commentaires -- et /* */),
   ce qui préserve indentation et commentaires.

Garde-fous (MergeBlocked)
-------------------------
- L'échafaudage commun (lignes 'equal') doit représenter une part substantielle :
  >= MIN_EQUAL_LINES lignes ET >= MIN_EQUAL_RATIO de la longueur du plus long SQL.
- Chaque hunk non-equal ne doit contenir QUE des expressions de colonnes
  (motif ' AS ', listes d'identifiants, continuations, commentaires). Toute ligne
  commençant par un mot-clé structurel (FROM/JOIN/WHERE/GROUP BY/ORDER BY/HAVING/
  LIMIT/UNION/SELECT/WITH/ON/')'/';') déclenche MergeBlocked avec diagnostic.
- Incohérence de virgule terminale entre les deux côtés d'un hunk -> MergeBlocked.

Limites connues
---------------
- Suppose un formatage « une expression de colonne par ligne ou liste d'identifiants » ;
  ne réécrit jamais l'échafaudage. Si les jumelles divergent structurellement
  (FROM/JOIN/WHERE différents), la fusion est refusée plutôt que devinée.
- La déduplication d'items est textuelle (espaces normalisés, commentaires ignorés,
  casefold) : deux expressions sémantiquement identiques mais écrites différemment
  ne seront pas dédupliquées (le SQL résultant échouerait alors sur alias dupliqué,
  ce que la vérification d'exécution détecte).

Vérification (compare_runs)
---------------------------
Compare le résultat d'exécution de la carte fusionnée avec celui d'une jumelle :
mêmes nombres de lignes, colonnes de la fusionnée ⊇ colonnes de la jumelle, et pour
chaque colonne de la jumelle valeurs identiques ligne à ligne (tri préalable par la
colonne de dimension, tolérance RELATIVE rel_tol pour les flottants — jamais
d'égalité stricte, les floats Snowflake varient entre runs).
"""

from __future__ import annotations

import difflib
import re

MIN_EQUAL_LINES = 20
MIN_EQUAL_RATIO = 0.10

_STRUCTURAL_RE = re.compile(
    r"(?i)^\s*("
    r"from\b|join\b|inner\b|left\b|right\b|full\b|cross\b|where\b|"
    r"group\s+by\b|order\s+by\b|having\b|limit\b|union\b|select\b|with\b|on\b|"
    r"\)|;"
    r")"
)


class MergeBlocked(Exception):
    """La fusion est refusée : diagnostic précis dans str(exc)."""


# ---------------------------------------------------------------------------
# Découpage d'un fragment de liste SELECT en items (virgules de profondeur 0)
# ---------------------------------------------------------------------------

def _split_top_level(text: str):
    """Découpe `text` aux virgules de profondeur 0 (hors (), '...', -- et /* */).

    Retourne (items, trailing) où `trailing` est True si le fragment se termine
    par une virgule de profondeur 0 (la liste continue dans le hunk suivant).
    Un éventuel reliquat final sans contenu (espaces/commentaires) est rattaché
    au dernier item.
    """
    items, buf = [], []
    depth = 0
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "'":  # chaîne SQL (les '' internes sont deux quotes successives)
            buf.append(ch)
            i += 1
            while i < n:
                buf.append(text[i])
                if text[i] == "'":
                    i += 1
                    break
                i += 1
            continue
        if ch == "-" and text[i : i + 2] == "--":  # commentaire de ligne
            j = text.find("\n", i)
            j = n if j == -1 else j
            buf.append(text[i:j])
            i = j
            continue
        if ch == "/" and text[i : i + 2] == "/*":  # commentaire bloc
            j = text.find("*/", i)
            j = n if j == -1 else j + 2
            buf.append(text[i:j])
            i = j
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            items.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1

    tail = "".join(buf)
    trailing = False
    if _norm_item(tail) == "":
        # le fragment finissait par une virgule (+ éventuels commentaires/espaces)
        trailing = bool(items)
        if items and tail:
            items[-1] += ","  # on ré-attache le reliquat (commentaires) ...
            items[-1] += tail  # ... après la virgule pour préserver le texte
            trailing = False  # la virgule est déjà réinsérée
    else:
        items.append(tail)
    return items, trailing


def _norm_item(item: str) -> str:
    """Forme normalisée d'un item pour déduplication : sans commentaires de ligne,
    espaces normalisés, casefold (identifiants SQL insensibles à la casse)."""
    lines = []
    for ln in item.splitlines():
        s = ln.strip()
        if not s or s.startswith("--"):
            continue
        lines.append(s)
    return re.sub(r"\s+", " ", " ".join(lines)).casefold()


# ---------------------------------------------------------------------------
# Garde-fous
# ---------------------------------------------------------------------------

def _check_hunk_lines(lines, side: str, hunk_desc: str):
    """Vérifie qu'un hunk non-equal ne contient que des expressions de colonnes."""
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("--"):
            continue
        if _STRUCTURAL_RE.match(s):
            raise MergeBlocked(
                f"Hunk {hunk_desc} côté {side} : ligne structurelle "
                f"(FROM/JOIN/WHERE/...) dans un bloc supposé colonnes-métriques : {s[:120]!r}"
            )
        if ";" in s.split("--", 1)[0]:
            raise MergeBlocked(
                f"Hunk {hunk_desc} côté {side} : point-virgule inattendu : {s[:120]!r}"
            )


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------

def merge_sqls(generic_sql: str, custom_sql: str) -> str:
    """Fusionne les SQL de deux cartes jumelles (générique, custom) -> SQL « toutes conversions ».

    Voir le docstring du module pour la méthode et les garde-fous.
    Lève MergeBlocked (avec diagnostic) si les jumelles ne respectent pas les invariants.
    Déterministe : même entrée -> même sortie.
    """
    a = generic_sql.splitlines()
    b = custom_sql.splitlines()
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()

    equal_lines = sum(i2 - i1 for tag, i1, i2, _, _ in ops if tag == "equal")
    longest = max(len(a), len(b)) or 1
    if equal_lines < MIN_EQUAL_LINES or equal_lines / longest < MIN_EQUAL_RATIO:
        raise MergeBlocked(
            f"Échafaudage commun insuffisant : {equal_lines} lignes 'equal' "
            f"({equal_lines / longest:.0%} du plus long SQL) ; "
            f"seuils : >= {MIN_EQUAL_LINES} lignes et >= {MIN_EQUAL_RATIO:.0%}. "
            "Les deux cartes ne sont probablement pas jumelles."
        )

    out: list[str] = []
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            out.extend(a[i1:i2])
            continue

        hunk_desc = f"a[{i1}:{i2}]/b[{j1}:{j2}] ({tag})"
        _check_hunk_lines(a[i1:i2], "générique", hunk_desc)
        _check_hunk_lines(b[j1:j2], "custom", hunk_desc)

        if tag == "delete":  # lignes seulement côté générique : on les garde
            out.extend(a[i1:i2])
            continue
        if tag == "insert":  # lignes seulement côté custom : on les garde
            out.extend(b[j1:j2])
            continue

        # tag == "replace" : union des items, générique PUIS custom, dédupliqués
        items_a, trail_a = _split_top_level("\n".join(a[i1:i2]))
        items_b, trail_b = _split_top_level("\n".join(b[j1:j2]))
        if trail_a != trail_b:
            raise MergeBlocked(
                f"Hunk {hunk_desc} : virgule terminale incohérente entre les deux côtés "
                f"(générique={trail_a}, custom={trail_b}) — structure de liste divergente."
            )
        seen = {_norm_item(it) for it in items_a}
        merged_items = list(items_a)
        for it in items_b:
            if _norm_item(it) not in seen:
                merged_items.append(it)
        text = ",".join(merged_items)
        if trail_a:
            text += ","
        out.extend(text.split("\n"))

    return "\n".join(out)


# ---------------------------------------------------------------------------
# Comparaison de résultats d'exécution
# ---------------------------------------------------------------------------

def _sort_rows(cols, rows, dim_col):
    idx = cols.index(dim_col)
    return sorted(rows, key=lambda r: (r[idx] is None, str(r[idx])))


def _values_equal(x, y, rel_tol):
    if x is None or y is None:
        return x is None and y is None
    if isinstance(x, bool) or isinstance(y, bool):
        return x == y
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        fx, fy = float(x), float(y)
        if fx == fy:
            return True
        return abs(fx - fy) <= rel_tol * max(abs(fx), abs(fy))
    return x == y


def compare_runs(merged_cols, merged_rows, twin_cols, twin_rows, dim_col, *,
                 rel_tol: float = 1e-9, twin_label: str = "twin"):
    """Compare le run de la carte fusionnée au run d'une jumelle.

    merged_cols / twin_cols : listes de noms de colonnes (résultat d'exécution).
    merged_rows / twin_rows : listes de lignes (listes de valeurs).
    dim_col : nom de la colonne de dimension (tri des lignes avant comparaison).

    Retourne (ok: bool, problems: list[str]). Vérifie :
    - même nombre de lignes ;
    - colonnes de la fusionnée ⊇ colonnes de la jumelle ;
    - pour CHAQUE colonne de la jumelle, valeurs identiques ligne à ligne
      (tolérance relative rel_tol pour les nombres, égalité stricte sinon).
    """
    problems = []
    if len(merged_rows) != len(twin_rows):
        problems.append(
            f"[{twin_label}] nombre de lignes : fusionnée={len(merged_rows)} vs jumelle={len(twin_rows)}"
        )
    missing = [c for c in twin_cols if c not in merged_cols]
    if missing:
        problems.append(f"[{twin_label}] colonnes absentes de la fusionnée : {missing}")
    if problems:
        return False, problems

    if dim_col not in merged_cols or dim_col not in twin_cols:
        return False, [f"[{twin_label}] colonne de dimension {dim_col!r} introuvable"]

    ms = _sort_rows(merged_cols, merged_rows, dim_col)
    ts = _sort_rows(twin_cols, twin_rows, dim_col)
    m_idx = {c: k for k, c in enumerate(merged_cols)}
    for col in twin_cols:
        t_i = twin_cols.index(col)
        m_i = m_idx[col]
        for r, (mr, tr) in enumerate(zip(ms, ts)):
            if not _values_equal(mr[m_i], tr[t_i], rel_tol):
                problems.append(
                    f"[{twin_label}] colonne {col!r} ligne {r} : "
                    f"fusionnée={mr[m_i]!r} vs jumelle={tr[t_i]!r}"
                )
                break  # un mismatch par colonne suffit au diagnostic
    return (not problems), problems
