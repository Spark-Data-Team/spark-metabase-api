#!/usr/bin/env python3
"""Logique pure de la migration de conversions (ancien positionnel -> nouveau nommé).
Aucune I/O réseau. Voir docs/superpowers/specs/2026-06-03-conversion-migration-design.md."""
from __future__ import annotations
import json, re
from collections import defaultdict

# --- Column inventory (authoritative, Snowflake information_schema 2026-06-03) ---
OLD_COUNT = ["CONVERSIONS"] + [f"CONVERSIONS_{n}" for n in range(1, 20)]
OLD_VALUE = ["CONVERSION_VALUE"] + [f"CONVERSION_{n}_VALUE" for n in range(1, 20)]
OLD_COLS = set(OLD_COUNT) | set(OLD_VALUE)

CUSTOM_COUNT = {n: f"CUSTOM_CONVERSIONS_{n}" for n in range(1, 16)}
CUSTOM_VALUE = {n: f"CUSTOM_CONVERSIONS_{n}_VALUE" for n in range(1, 16)}
NAMED_COL = {
    "Purchases": ("PURCHASES", "PURCHASES_VALUE"),
    "Add to cart": ("ADD_TO_CARTS_NEW", "ADD_TO_CARTS_VALUE_NEW"),
    "Initiate checkouts": ("INITIATE_CHECKOUTS", "INITIATE_CHECKOUTS_VALUE"),
    "Content views OR View Item": ("CONTENT_VIEWS", None),
    "Sign ups": ("SIGN_UPS", None),
    "Leads": ("LEADS", "LEADS_VALUE"),
    "Marketing Qualified Leads": ("MARKETING_QUALIFIED_LEADS", "MARKETING_QUALIFIED_LEADS_VALUE"),
    "Sales Qualified Leads": ("SALES_QUALIFIED_LEADS", "SALES_QUALIFIED_LEADS_VALUE"),
    "Offline sales": ("OFFLINE_SALES", "OFFLINE_SALES_VALUE"),
    "App installs": ("APP_INSTALLS_NEW", "APP_INSTALL_VALUE"),
    "Search visits (combo organic + sea custom conv meta)": ("SEARCH_VISITS_COMBO", None),
    "Organic search visits (custom conv meta)": ("ORGANIC_SEARCH_VISITS", None),
    "Paid search visits (custom conv meta)": ("PAID_SEARCH_VISITS", None),
}
NEW_COLS = set()
for n in range(1, 16):
    NEW_COLS |= {CUSTOM_COUNT[n], CUSTOM_VALUE[n]}
for _c, _v in NAMED_COL.values():
    NEW_COLS.add(_c)
    if _v:
        NEW_COLS.add(_v)

def _rx(cols):
    return re.compile(r"(?<![A-Z0-9_])(" + "|".join(sorted(cols, key=len, reverse=True)) + r")(?![A-Z0-9_])")
_OLD_RX, _NEW_RX = _rx(OLD_COLS), _rx(NEW_COLS)

_SQL_LITERAL_RX = re.compile(r"'(?:[^']|'')*'")

def _mask_literals(text):
    """Neutralise les littéraux SQL '...' (détection/substitution ne doivent jamais y toucher:
    WHERE event = 'conversions_1' est une VALEUR, pas une colonne)."""
    parts = []
    def _repl(m):
        parts.append(m.group(0))
        return f"\x00L{len(parts) - 1}\x00"
    return _SQL_LITERAL_RX.sub(_repl, text), parts

def _unmask_literals(text, parts):
    for i, p in enumerate(parts):
        text = text.replace(f"\x00L{i}\x00", p)
    return text

def native_and_tags(card):
    """(sql, template-tags dict) — tolère natif legacy, stages pMBQL, et legacy_query."""
    dq = card.get("dataset_query") or {}
    if dq.get("type") == "native":
        n = dq.get("native") or {}
        return n.get("query") or "", (n.get("template-tags") or {})
    for st in dq.get("stages") or []:
        if st.get("lib/type") == "mbql.stage/native":
            return st.get("native") or "", (st.get("template-tags") or {})
    lq = card.get("legacy_query")
    if isinstance(lq, str):
        try:
            lq = json.loads(lq)
        except Exception:
            lq = {}
        if isinstance(lq, dict) and lq.get("type") == "native":
            n = lq.get("native") or {}
            return n.get("query") or "", (n.get("template-tags") or {})
    return "", {}

def old_conversion_columns(sql):
    masked, _ = _mask_literals(sql or "")
    return set(_OLD_RX.findall(masked.upper()))

def new_conversion_columns(sql):
    masked, _ = _mask_literals(sql or "")
    return set(_NEW_RX.findall(masked.upper()))

# Tables that actually hold conversion metrics (the "platform/source"); a swap is only
# valid between cards reading the SAME source table (e.g. a GA4 card must not become a
# campaign_daily_metrics card even if the conversion mapping matches).
METRIC_TABLES = {
    # schema `global` = ads platforms (Google/Meta/TikTok Ads…), several granularities
    "global.campaign_daily_metrics", "global.campaign_daily_metrics_per_device",
    "global.campaign_daily_geographical_metrics", "global.campaign_breakdown_daily_metrics",
    "global.campaign_daily_url_metrics", "global.search_adgroup_daily_metrics",
    "global.social_ad_daily_metrics", "global.social_adset_daily_metrics",
    # schema `analytics` = GA4 / analytics
    "analytics.google__analytics_metrics", "analytics.google__analytics_per_device",
    "analytics.google__analytics_per_landing_page", "analytics.google__analytics_per_location",
    "analytics.google__analytics_url_groups", "analytics.google__analytics_accounts",
    # misc
    "google.google__keyword_metrics",
}
# Source family (ads / analytics / crm) — a swap must stay within the same exact table,
# but the family is useful for reporting/coverage.
def source_family(table):
    if not table:
        return None
    schema = table.split(".", 1)[0]
    return {"global": "ads", "analytics": "analytics", "google": "ads"}.get(schema, schema)
_FROMJOIN_RX = re.compile(r"(?:\bfrom|\bjoin)\s+([a-z0-9_]+\.[a-z0-9_]+)(?:\s+(?:as\s+)?([a-z0-9_]+))?")
_SQL_KW = {"on", "where", "left", "right", "inner", "outer", "full", "cross", "join",
           "group", "order", "as", "using", "and", "or", "select", "with"}

def conversion_source(sql):
    """The metric source table the card's conversion column comes from, or None.
    Deterministic: resolves table aliases (FROM t AS a -> a.col), prefers the table the
    conversion column is qualified to; campaign_daily_metrics wins remaining ties, then
    alphabetical order (never set-iteration order)."""
    low = (sql or "").lower()
    qual, present = {}, []
    for t, a in _FROMJOIN_RX.findall(low):
        if t in METRIC_TABLES:
            if t not in present:
                present.append(t)
            qual[t] = t
            qual[t.split(".", 1)[1]] = t
            if a and a not in _SQL_KW:
                qual[a] = t
    if not present:
        return None
    if len(present) == 1:
        return present[0]
    for m in re.finditer(r"([a-z0-9_\.]+)\.([a-z0-9_]+)", low):
        if m.group(2).upper() in OLD_COLS or m.group(2).upper() in NEW_COLS:
            t = qual.get(m.group(1)) or qual.get(m.group(1).split(".")[-1])
            if t:
                return t
    if "global.campaign_daily_metrics" in present:
        return "global.campaign_daily_metrics"
    return sorted(present)[0]

def has_opaque_refs(sql):
    """True si le SQL référence un snippet ({{snippet: ...}}) ou une carte source ({{#123}}) :
    leur contenu est invisible ici et peut cacher des colonnes de conversion."""
    low = (sql or "").lower()
    return bool(re.search(r"\{\{\s*snippet\s*:", low) or re.search(r"\{\{\s*#\d+", low))

def tag_field_map(card):
    """{template-tag name -> field ref} des field-filters de la carte. Réfs par id
    (recherche en profondeur, dernier entier) ou par NOM ('name:<champ>')."""
    _, tags = native_and_tags(card)
    out = {}
    for name, d in (tags or {}).items():
        dim = (d or {}).get("dimension")
        if not isinstance(dim, list):
            continue
        ints, strs = [], []
        stack = [dim]
        while stack:
            x = stack.pop(0)
            if isinstance(x, list):
                stack = list(x) + stack
            elif isinstance(x, int):
                ints.append(x)
            elif isinstance(x, str) and x not in ("field", "field-id", "dimension", "template-tag"):
                strs.append(x)
        if ints:
            out[name] = ints[-1]
        elif strs:
            out[name] = f"name:{strs[0]}"
    return out

def tag_rename_map(old_card, new_card):
    """{old_tag -> new_tag} for filters renamed between cards but pointing to the SAME
    Snowflake field (e.g. 'location' -> 'campaign_location'). Lets a swap re-wire a filter
    whose template-tag name changed, instead of breaking it."""
    o, n = tag_field_map(old_card), tag_field_map(new_card)
    by_field = {}
    for name, fid in n.items():
        by_field.setdefault(fid, name)
    return {name: by_field[fid] for name, fid in o.items() if name not in n and fid in by_field}

def incompatible_wired_tags(old_card, new_card, wired_tags, renames=None):
    """Tags câblés au dashboard dont le TYPE change entre l'ancienne et la nouvelle carte
    (ex. time_period: 'dimension' -> 'temporal-unit'): le paramètre du dashboard ne peut
    plus les piloter, le filtre meurt silencieusement -> swap à refuser.
    Retourne {tag: (type_ancien, type_nouveau)}."""
    renames = renames or {}
    _, ot = native_and_tags(old_card)
    _, nt = native_and_tags(new_card)
    bad = {}
    for t in wired_tags:
        o, n = ot.get(t), nt.get(renames.get(t, t))
        if o and n and o.get("type") != n.get("type"):
            bad[t] = (o.get("type"), n.get("type"))
    return bad

# --- Type-axis (Airtable slot -> new named) ---
TYPE_TO_SLOT = {"Main conversion": 0}
_ORD = ["1st", "2nd", "3rd"] + [f"{n}th" for n in range(4, 20)]
for _i, _o in enumerate(_ORD, start=1):
    TYPE_TO_SLOT[f"{_o} conversion"] = _i

UNMAPPED = "__UNMAPPED__"
CONFLICT = "__CONFLICT__"

def slot_old_columns(slot):
    if slot == 0:
        return ("CONVERSIONS", "CONVERSION_VALUE")
    return (f"CONVERSIONS_{slot}", f"CONVERSION_{slot}_VALUE")

def new_type_columns(new_type):
    m = re.match(r"Custom (\d+)$", new_type or "")
    if m:
        n = int(m.group(1))
        return (CUSTOM_COUNT.get(n), CUSTOM_VALUE.get(n))
    return NAMED_COL.get(new_type, (None, None))

def _slot_of(col):
    if col in ("CONVERSIONS", "CONVERSION_VALUE"):
        return 0
    m = re.search(r"(\d+)", col)
    return int(m.group(1)) if m else None

def substitution_map(old_cols, client_mapping):
    """For each OLD conversion column the card uses, the NEW column to substitute it with,
    via the client's slot->new_type. Returns (sub_map, unmapped_cols). A column whose slot
    has no usable mapping (absent / UNMAPPED / CONFLICT) is left in `unmapped`."""
    sub, unmapped = {}, []
    for col in old_cols:
        slot = _slot_of(col)
        nt = client_mapping.get(slot) if slot is not None else None
        if nt is None or nt in (UNMAPPED, CONFLICT):
            unmapped.append(col)
            continue
        cnt, val = new_type_columns(nt)
        new = val if (col.endswith("_VALUE") or col == "CONVERSION_VALUE") else cnt
        if new:
            sub[col] = new
        else:
            unmapped.append(col)
    return sub, unmapped

def apply_substitution(text, sub_map):
    """Replace each OLD column by its NEW column in SQL/JSON text, whole-word and
    case-preserving. Longest keys first; guarded so CONVERSIONS doesn't match inside
    CONVERSIONS_1, nor CONVERSIONS_1 inside CONVERSIONS_10, nor re-hit CUSTOM_CONVERSIONS_1.
    SQL string literals '...' are never rewritten (same masking as detection)."""
    if not text:
        return text
    masked, parts = _mask_literals(text)
    for old in sorted(sub_map, key=len, reverse=True):
        new = sub_map[old]
        masked = re.sub(rf"(?<![A-Za-z0-9_])(?i:{re.escape(old)})(?![A-Za-z0-9_])",
                        lambda m, n=new: n.lower() if m.group(0).islower() else n.upper(), masked)
    return _unmask_literals(masked, parts)


def _select_item_alias(item_text):
    """Alias d'un item SELECT : l'identifiant après le dernier ` AS ` (ex. `END AS conversions_2_evolution`),
    sinon un item « colonne nue » (passthrough de CTE). None si non parsable. Tolère le multi-ligne."""
    t = item_text.strip()
    m = re.search(r"\bAS\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", t, re.IGNORECASE)
    if m:
        return m.group(1)
    m2 = re.fullmatch(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*", t)
    return m2.group(1) if m2 else None


def _mask_sql(text):
    """Masque littéraux '...' ET commentaires de ligne `-- …` en placeholders \\x00M<n>\\x00 (1 passe,
    littéral prioritaire pour ne pas couper un -- à l'intérieur d'un littéral). Réversible via _unmask_sql."""
    parts = []
    def repl(m):
        parts.append(m.group(0))
        return f"\x00M{len(parts) - 1}\x00"
    return re.sub(r"'(?:[^']|'')*'|--[^\n]*", repl, text), parts


def _unmask_sql(masked, parts):
    return re.sub(r"\x00M(\d+)\x00", lambda m: parts[int(m.group(1))], masked)


def _select_spans(masked):
    """Spans (start,end) du CONTENU de chaque liste SELECT (entre `SELECT` et son `FROM` au MÊME
    niveau de parenthèses). Gère CTE imbriquées et UNION (chaque SELECT a son FROM)."""
    spans, depth, open_sel = [], 0, []
    for m in re.finditer(r"\(|\)|\bSELECT\b|\bFROM\b", masked, re.IGNORECASE):
        t = m.group(0).upper()
        if t == "(":
            depth += 1
        elif t == ")":
            depth -= 1
        elif t == "SELECT":
            open_sel.append((depth, m.end()))
        elif t == "FROM" and open_sel and open_sel[-1][0] == depth:
            _, start = open_sel.pop()
            spans.append((start, m.start()))
    return spans


def _split_top_level(seg):
    """Découpe un segment de liste SELECT en items, sur les virgules au niveau de parenthèses 0
    (les virgules internes COALESCE(a,b) restent dans l'item). Renvoie des plages (a,b)."""
    out, depth, last = [], 0, 0
    for i, ch in enumerate(seg):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append((last, i)); last = i + 1
    out.append((last, len(seg)))
    return out


def _refs_any(text, names):
    """True si `text` référence (mot entier, insensible à la casse) un des `names`."""
    return any(re.search(rf"(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])", text, re.IGNORECASE)
               for n in names)


def drop_conversion_selects(sql):
    """Brique b — retire du SQL généré les ITEMS SELECT qui dépendent d'une colonne de conversion
    POSITIONNELLE NON mappée (CONVERSIONS / CONVERSIONS_N / CONVERSION_N_VALUE / CONVERSION_VALUE).
    Objectif : après `apply_substitution` (slots MAPPÉS → colonnes nommées), supprimer les slots NON
    mappés pour que la carte ne référence PLUS aucune colonne positionnelle → Iron Law (« garder
    seulement les conversions réelles »).

    Parseur SELECT-aware + CASCADE d'alias (fixpoint) : un item SELECT est retiré s'il référence un
    nom « tué » ; son alias rejoint alors l'ensemble tué → on retire aussi les colonnes DÉRIVÉES
    (`current_conversions_N`, `*_evolution`, `cac_N`, `cr_N`…) sur tous les CTE, y compris les items
    CASE MULTI-LIGNES. Les slots MAPPÉS et leurs dérivés sont préservés (jamais dans l'ensemble tué).

    Self-safe (pur, zéro régression) — renvoie le SQL INCHANGÉ si : aucune colonne positionnelle ;
    pas de liste SELECT détectée ; une liste serait entièrement vidée ; il reste une colonne
    positionnelle après coup ; ou une référence pendante vers un alias supprimé subsiste. (Filet
    ultime en aval : render_ok archive tout SQL cassé.)"""
    if not sql:
        return sql
    seed = {c.lower() for c in old_conversion_columns(sql)}
    if not seed:
        return sql
    masked, parts = _mask_sql(sql)
    spans = _select_spans(masked)
    if not spans:
        return sql
    span_items, all_items = [], []
    for si, (s, e) in enumerate(spans):
        seg = masked[s:e]
        items = []
        for a, b in _split_top_level(seg):
            text = seg[a:b]
            if not text.strip():
                continue
            al = _select_item_alias(text)
            items.append({"text": text, "alias": al.lower() if al else None, "drop": False})
        span_items.append(items); all_items.extend(items)

    kill, changed = set(seed), True
    while changed:
        changed = False
        for it in all_items:
            if not it["drop"] and _refs_any(it["text"], kill):
                it["drop"] = True
                if it["alias"]:
                    kill.add(it["alias"])
                changed = True

    out = masked
    for si in range(len(spans) - 1, -1, -1):      # de la fin au début : indices stables
        items = span_items[si]
        kept = [it["text"] for it in items if not it["drop"]]
        if len(kept) == len(items):
            continue
        if not kept:
            return sql                            # liste SELECT vidée -> SQL invalide -> no-op
        s, e = spans[si]
        seg = masked[s:e]
        lead = seg[:len(seg) - len(seg.lstrip())]
        trail = seg[len(seg.rstrip()):]
        body = ("," + lead).join(t.strip() for t in kept)
        out = out[:s] + lead + body + trail + out[e:]

    result = _unmask_sql(out, parts)
    if old_conversion_columns(result):            # positionnelle subsistante (hors liste SELECT) -> no-op
        return sql
    dropped_aliases = {it["alias"] for it in all_items if it["drop"] and it["alias"]}
    masked_result, _ = _mask_sql(result)
    if _refs_any(masked_result, dropped_aliases):  # référence pendante -> drop non sûr -> no-op
        return sql
    return result


def _close(a, b, tol=1e-6):
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return a == b
    return a == b or abs(a - b) <= tol * max(abs(a), abs(b), 1e-12)


def value_diffs(old_cols, old_rows, new_cols, new_rows, sub_map, tol=1e-6):
    """Garde-fou VALEUR de generate_fallback (= policy user « écart de valeur → revue »). Pour chaque
    slot mappé (sub_map OLD→NEW), compare la SOMME de la colonne entre la carte ORIGINALE (colonne
    positionnelle) et la carte GÉNÉRÉE (colonne nommée) — comparaison **indépendante de l'ordre des
    lignes** (robuste aux cartes sans ORDER BY). Renvoie [(old_col, new_col, old_sum, new_sum)] pour
    les colonnes dont la somme diffère (> tolérance). Vide = fidèle. Pur. Une colonne absente d'un des
    deux jeux est ignorée (non comparable, pas un écart). Choix SOMME (vs cellule) : le risque réel est
    un nommé qui compte AUTREMENT que le positionnel (écart systématique, ex. Toploc/TuneCore) — la
    somme le capte sans faux positif d'ordre."""
    def colsum(cols, rows, name):
        idx = {str(c).upper(): i for i, c in enumerate(cols)}
        i = idx.get(name.upper())
        if i is None:
            return None
        return sum(r[i] for r in rows if isinstance(r[i], (int, float)))
    diffs = []
    for oc, nc in sub_map.items():
        os_, ns_ = colsum(old_cols, old_rows, oc), colsum(new_cols, new_rows, nc)
        if os_ is None or ns_ is None:
            continue
        if not _close(os_, ns_, tol):
            diffs.append((oc, nc, os_, ns_))
    return diffs


def repoint_visualizer_source(viz_settings, old_cid, new_cid):
    """Dashcard « visualizer » (Metabase) : la viz combine des colonnes de cartes SOURCES,
    référencées par "card:<id>" dans visualization.columnValuesMapping (et dataSources). Quand
    on repointe un dashcard d'une carte old_cid -> new_cid, il faut AUSSI réécrire ces réfs,
    sinon le visualizer source l'ANCIENNE carte (positionnelle) = tuile vide. Réécrit le token
    EXACT "card:<old_cid>" -> "card:<new_cid>" (n'altère pas card:<old_cid>X). No-op si viz
    None / sans cette réf / old_cid==new_cid. Pur."""
    if not viz_settings or old_cid is None or new_cid is None or old_cid == new_cid:
        return viz_settings
    s = json.dumps(viz_settings, ensure_ascii=False)
    token = f'"card:{old_cid}"'
    if token not in s:
        return viz_settings
    return json.loads(s.replace(token, f'"card:{new_cid}"'))

# Clés de viz qui portent un LIBELLÉ HUMAIN (jamais une réf de colonne) -> à NE PAS substituer.
VIZ_LABEL_KEYS = frozenset({
    "card.title", "title", "title_text", "column_title",
    "graph.x_axis.title_text", "graph.y_axis.title_text",
})

def substitute_viz(viz, sub_map):
    """Substitue les RÉFÉRENCES de colonnes dans une viz (graph.metrics/dimensions, clés
    series_settings & column_settings, scalar.field, table.columns[].name…) SANS toucher aux
    LIBELLÉS humains (card.title, titres d'axes/séries, column_title). La substitution brute
    sur le JSON entier corrompait les titres : un card.title='Conversions' devenait 'PURCHASES'.
    Récursif ; substitue les CLÉS (réfs) et les VALEURS string, mais garde intacte la valeur
    d'une clé-libellé. No-op si viz vide. Pur."""
    if not viz:
        return viz
    def walk(node):
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                nk = apply_substitution(k, sub_map) if isinstance(k, str) else k
                out[nk] = v if (isinstance(k, str) and k in VIZ_LABEL_KEYS) else walk(v)
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        if isinstance(node, str):
            return apply_substitution(node, sub_map)
        return node
    return walk(viz)

# libellés de tuile GÉNÉRIQUES (conversion non nommée) -> remplaçables par la conversion nommée.
# Les libellés MÉTIER choisis par le consultant (« Demandes de devis », « Ventes »…) sont préservés.
GENERIC_CONV_TITLES = frozenset({"conversions", "conversion", "main conversion"})

def conversion_display_names(old_cols, cmap):
    """Noms d'affichage (Airtable) des conversions NOMMÉES qu'une tuile mesure : pour chaque ancienne
    colonne conversion -> slot -> cmap[slot]. `old_cols` = sub_map (dict, clés=colonnes) ou itérable
    de colonnes. Ignore les slots non mappés / en conflit."""
    cols = old_cols.keys() if isinstance(old_cols, dict) else old_cols
    out = set()
    for c in cols:
        v = cmap.get(_slot_of(c))
        if v and v not in ("__UNMAPPED__", "__CONFLICT__"):
            out.add(v)
    return out

def relabel_conversion_title(old_title, display_names):
    """Si old_title est un libellé de conversion GÉNÉRIQUE et que la tuile mesure UNE seule conversion
    nommée, renvoie son nom d'affichage ; sinon garde old_title (préserve les libellés métier). Pur."""
    uniq = sorted(n for n in display_names if n)
    if len(uniq) == 1 and str(old_title or "").strip().lower() in GENERIC_CONV_TITLES:
        return uniq[0]
    return old_title

def normalize_period_label(s):
    """Canonicalise un libellé de PÉRIODE pour aligner des formats différents (ex. '2026 - W22'
    et '2026_22' -> (2026, 22)) : extrait les groupes de chiffres dans l'ordre. Sans chiffre,
    renvoie la chaîne nettoyée majuscule (= libellé exact). Sûr à granularité FIXÉE (semaine vs
    mois ne se télescopent pas dans une même comparaison). Pur."""
    s = str(s).strip()
    nums = re.findall(r"\d+", s)
    return tuple(int(n) for n in nums) if nums else s.upper()

def is_required_param_error(err):
    """True si l'erreur d'exécution = un paramètre REQUIS non fourni (param obligatoire sans défaut,
    fourni par le dashboard à l'usage) et NON une vraie erreur SQL : « pick a value for X », « before
    this query can run », « missing required parameter(s) X ». La carte est alors structurellement OK
    (à NE PAS archiver). Pur."""
    low = str(err or "").lower()
    return ("pick a value" in low or "before this query can run" in low
            or "missing required parameter" in low)

def split_multiselect_pairs(type_cell, new_type_cell):
    """Aplatit une ligne Airtable où `type` et `new_type` sont des multi-select (CSV =
    valeurs jointes par virgule). Retourne (pairs, ambiguous) :
      pairs     = [(type, new_type | None)] ;
      ambiguous = True si on ne peut PAS pairer sûrement (cardinalités ≠ et non vides) -> Gaby.
    Pairing POSITIONNEL quand les cardinalités correspondent (convention de saisie observée :
    'Main conversion,1st conversion' / 'Purchases,Custom 1'). Un `type` sans `new_type` = slot
    non mappé (None), pas ambigu."""
    types = [t.strip() for t in (type_cell or "").split(",") if t.strip()]
    news = [n.strip() for n in (new_type_cell or "").split(",") if n.strip()]
    if not types:
        return [], False
    if len(news) == len(types):
        return list(zip(types, news)), False
    if not news:
        return [(t, None) for t in types], False
    return [(t, None) for t in types], True  # cardinalités ≠ -> pairing impossible -> à trancher (Gaby)


def build_client_mappings(records):
    """records: [{client, type, new_type}] -> {client: {slot: new_type | UNMAPPED | CONFLICT}}."""
    seen = defaultdict(lambda: defaultdict(set))
    for r in records:
        client, typ = r.get("client"), r.get("type")
        if not client or typ not in TYPE_TO_SLOT:
            continue
        slot = TYPE_TO_SLOT[typ]
        nt = r.get("new_type")
        seen[client][slot]
        if nt:
            seen[client][slot].add(nt)
    out = {}
    for client, slots in seen.items():
        out[client] = {}
        for slot, nts in slots.items():
            out[client][slot] = (next(iter(nts)) if len(nts) == 1
                                 else CONFLICT if len(nts) > 1 else UNMAPPED)
    return out

# --- Shape axis (display x metric x breakdown) ---
_BREAKDOWN = [("date", "date"), ("channel", "channel"), ("network", "network"),
              ("categor", "category"), ("countr", "country"), ("location", "location"),
              ("device", "device"), ("product", "product"), ("url", "url"), ("type", "type"),
              ("adset", "adset"), ("adgroup", "adgroup"), ("placement", "placement"),
              ("segment", "segment"), ("medium", "medium"), ("page", "page"),
              ("week", "week"), ("month", "month"), ("keyword", "keyword"), ("audience", "audience")]

def _breakdown_tokens(text, found):
    """Ajoute les labels de breakdown trouvés dans `text` (déjà en minuscules).
    'conversion type' est distingué de 'campaign type' (sinon collision sur 'type')."""
    if "conversion type" in text or "conversion_type" in text:
        found.add("conversion_type")
        text = text.replace("conversion type", " ").replace("conversion_type", " ")
    for needle, label in _BREAKDOWN:
        if needle in text:
            found.add(label)
    # 'by campaign' seul (sans channel/type/...): needle trop générique pour la boucle
    if not found and "campaign" in text:
        found.add("campaign")
    return found

def metric_kind(name):
    n = (name or "").upper()
    if "COÛT PAR" in n or "COUT PAR" in n:  # FR: «Coût par conversion/acquisition» = CAC
        return "CAC"
    for k in ("ROAS", "CAC", "COS", "CPA", "CPI", "CTR"):
        if re.search(rf"\b{k}\b", n):
            return k
    if re.search(r"\bCR\b", n) or "RATE" in n or "TAUX" in n:  # FR: «Taux de …»
        return "RATE"
    # AVG before VALUE: "Avg X value" / «Valeur moyenne» / «Panier moyen» is an average
    if "AVG" in n or "AVERAGE" in n or "MOYEN" in n:
        return "AVG"
    if "VALUE" in n or "VALEUR" in n or "REVENU" in n:
        return "VALUE"
    return "COUNT"

def _breakdown(name, viz):
    found = set()
    src = (name or "").lower()
    m = re.search(r"\bby\b(.+)$", src)
    if m:
        _breakdown_tokens(m.group(1), found)
    for d in (viz or {}).get("graph.dimensions") or []:
        if isinstance(d, str):
            _breakdown_tokens(d.lower(), found)
    return tuple(sorted(found))

_SCALAR_DISPLAYS = {"scalar", "smartscalar", "gauge", "progress"}

def card_breakdown(card):
    display = card.get("display") or "?"
    # single-value displays have no breakdown -> ignore leftover graph.dimensions.
    viz = None if display in _SCALAR_DISPLAYS else card.get("visualization_settings")
    return _breakdown(card.get("name"), viz)

def card_shape(card):  # kept for back-compat
    return (card.get("display") or "?", metric_kind(card.get("name")), card_breakdown(card))

def series_kind(name):
    """Reduce one displayed-series name to its metric KIND, stripping the conversion identity
    (e.g. 'CAC_CUSTOM_CONVERSIONS_1' -> CAC, 'CUSTOM_CONVERSIONS_1' -> CONV, 'COST' -> COST)."""
    n = (name or "").upper()
    if "COST" in n or "SPEND" in n:  # before COS: "COST" contains "COS"
        return "COST"
    for k in ("ROAS", "CAC", "COS", "CPA", "CPI", "CTR", "CPC", "CPM"):
        if k in n:
            return k
    if re.search(r"\bCR\b", n) or n.startswith("CR") or "_CR_" in n or "RATE" in n or "TAUX" in n:
        return "CR"
    # AVG before VALUE (même règle que metric_kind): AVG_CONVERSION_1_VALUE est une moyenne
    if "AVG" in n or "AVERAGE" in n or "MOYEN" in n:
        return "AVG"
    if "VALUE" in n or "VALEUR" in n or "REVENU" in n:  # série 'revenue' = conversion_value
        return "VALUE"
    return "CONV"  # bare conversion count / purchases / leads / etc.

_TABLE_BASE = {"IMPRESSIONS", "CLICKS", "COST", "CTR", "CPC", "CPM"}

def _table_old_kind(col):
    """(kind, slot) d'une colonne de vieux tableau (préfixe CURRENT_ retiré).
    kind ∈ {base, count, cr, cac, value, avgvalue, roas, None} ; slot 0=main, n positionnel."""
    c = (col or "").upper()
    if c.startswith("CURRENT_"):
        c = c[len("CURRENT_"):]
    if c in _TABLE_BASE:
        return ("base", None)
    if c in ("AVG_CONV_VALUE", "AVG_CONVERSION_VALUE", "AVG_REVENUE"):  # avant 'value'
        return ("avgvalue", 0)
    if c in ("CONVERSIONS",):
        return ("count", 0)
    if c == "CONVERSION_RATE":  # alias de CONV_RATE (main)
        return ("cr", 0)
    if c == "REVENUE":          # alias de CONVERSION_VALUE (main)
        return ("value", 0)
    m = re.fullmatch(r"CONVERSIONS_(\d+)", c)
    if m:
        return ("count", int(m.group(1)))
    if c == "CONV_RATE":
        return ("cr", 0)
    m = re.fullmatch(r"CR_(\d+)", c)
    if m:
        return ("cr", int(m.group(1)))
    if c == "CAC":
        return ("cac", 0)
    m = re.fullmatch(r"CAC_(\d+)", c)
    if m:
        return ("cac", int(m.group(1)))
    if c in ("CONVERSION_VALUE", "CONV_VALUE"):
        return ("value", 0)
    m = re.fullmatch(r"CONV(?:ERSION)?_(\d+)_VALUE", c)
    if m:
        return ("value", int(m.group(1)))
    if c == "ROAS":
        return ("roas", 0)
    return (None, None)

def _is_table_dim(base):
    # dimension de breakdown : préfixée CAMPAIGN_ ou nom nu (channel/network/...)
    return (base in ("DATE", "TIME_PERIOD", "URL", "CHANNEL", "NETWORK", "CATEGORY",
                     "TYPE", "PRODUCT", "NAME", "LOCATION", "DEVICE")
            or base.startswith("CAMPAIGN_"))

def _new_conv_col(kind, base_token, evo=False):
    # côté neuf : valeur courante = CURRENT_<...> ; évolution = <...>_EVOLUTION (sans CURRENT_)
    if kind == "avgvalue":
        return f"AVG_{base_token}_VALUE_EVOLUTION" if evo else f"CURRENT_AVG_{base_token}_VALUE"
    suf = {"count": "", "cr": "_CR", "cac": "_CAC", "value": "_VALUE", "roas": "_ROAS"}[kind]
    return f"{base_token}{suf}_EVOLUTION" if evo else f"CURRENT_{base_token}{suf}"

def map_table_columns(old_visible, client_mapping, new_cols, dimension_new):
    """Mappe les colonnes VISIBLES d'un vieux tableau multi-slot vers les colonnes
    de la famille mixte (toutes conversions). Retourne (mapping {old->new}, unmapped[]).
    - dimension (DATE/CAMPAIGN_*/...) -> dimension_new
    - base (cost/impressions/...) -> CURRENT_<base>
    - métrique de conversion (slot 0=main, n positionnel) -> via mapping client Airtable
      slot->new_type (Purchases/Custom k), puis colonne CURRENT_<token>[_CR/_CAC/_VALUE/_ROAS].
    Une colonne sans mapping client, ou dont la cible n'existe pas dans new_cols, va en unmapped
    (le moteur garde alors l'ancien tableau / signale)."""
    new_cols = {str(c).upper() for c in new_cols}
    mapping, unmapped = {}, []
    for col in old_visible:
        c = col.upper()
        evo = c.endswith("_EVOLUTION")
        cbase = c[:-len("_EVOLUTION")] if evo else c
        base = cbase[len("CURRENT_"):] if cbase.startswith("CURRENT_") else cbase
        kind, slot = _table_old_kind(cbase)
        if kind is None:
            target = (dimension_new if (not evo and _is_table_dim(base)) else None)
        elif kind == "base":
            target = f"{base}_EVOLUTION" if evo else f"CURRENT_{base}"
        else:
            nt = client_mapping.get(slot)
            if nt in (None, UNMAPPED, CONFLICT):
                target = None
            else:
                base_token = new_type_columns(nt)[0]
                target = _new_conv_col(kind, base_token, evo) if base_token else None
        if target and target.upper() in new_cols:
            mapping[col] = target
        else:
            unmapped.append(col)
    return mapping, unmapped

def series_display_map(old_metrics, new_metrics):
    """Mappe chaque série AFFICHÉE de l'ancienne carte vers UNE série de la nouvelle,
    par nature de métrique (series_kind), en préférant les variantes non
    BRAND_EXCLUDED sauf si l'ancienne série est elle-même hors-brand. Permet de
    réutiliser une carte 11673 plus riche en MASQUANT ses séries en trop au niveau
    du dashcard (graph.metrics override). None si ambigu, manquant ou non injectif."""
    out = []
    for om in old_metrics or []:
        kind = series_kind(om)
        want_brand = "BRAND_EXCLUDED" in str(om).upper()
        cands = [nm for nm in new_metrics or [] if series_kind(nm) == kind
                 and ("BRAND_EXCLUDED" in str(nm).upper()) == want_brand]
        if len(cands) != 1:
            return None
        out.append(cands[0])
    if len(set(out)) != len(out):
        return None
    return out

_BRAND_ATOM = re.compile(
    r"LOWER\(\s*coalesce\(\s*([A-Za-z0-9_\.]*?)campaign_(\w+)\s*,\s*''\s*\)\s*\)\s*NOT\s+LIKE\s*'%brand%'",
    re.I)
_BRAND_CAT_STRICT = re.compile(
    r"\s+AND\s+LOWER\(TRIM\(coalesce\([A-Za-z0-9_\.]*?campaign_category,''\)\)\) != 'brand'")
_BRAND_STRICT_ATOM = re.compile(
    r"LOWER\(TRIM\(coalesce\([A-Za-z0-9_\.]*?campaign_category,''\)\)\)\s*!=\s*'brand'", re.I)

def strip_brand_atoms(sql):
    """Remplace tout atome d'exclusion brand par un marqueur §B§ et fusionne les
    « §B§ AND §B§ » : deux SQL qui ne diffèrent QUE par leur clause brand deviennent
    identiques. Gate du batch — strip(old)==strip(new) prouve qu'on n'a touché à
    rien d'autre que la clause brand."""
    s = _BRAND_STRICT_ATOM.sub("§B§", sql or "")
    s = _BRAND_ATOM.sub("§B§", s)
    return re.sub(r"§B§(\s+AND\s+§B§)+", "§B§", s)

def fix_brand_clause(sql):
    """Règle métier FINALE (validée 2026-06-12) : une campagne est « brand » si
    campaign_TYPE contient brand OU si campaign_CATEGORY vaut exactement 'Brand'
    (égalité stricte — un LIKE attraperait « Push Brand To Media », « Branding »…).
    L'exclusion canonique émise est donc la paire :
      LOWER(coalesce(<p>campaign_type,'')) NOT LIKE '%brand%'
      AND LOWER(TRIM(coalesce(<p>campaign_category,''))) != 'brand'
    Tout autre atome NOT LIKE '%brand%' (channel/category/location/...) est faux
    et remplacé. Préfixe d'alias préservé. Idempotent (sa sortie se reconnaît :
    l'atome catégorie-stricte est retiré puis ré-émis)."""
    # 1. retire l'atome catégorie-stricte (sortie d'un passage précédent)
    out = _BRAND_CAT_STRICT.sub("", sql or "")
    # 2. canonise chaque atome fautif vers campaign_type (préfixe préservé)
    out = _BRAND_ATOM.sub(
        lambda m: f"LOWER(coalesce({m.group(1)}campaign_type,'')) NOT LIKE '%brand%'", out)
    # 3. déduplique les atomes type identiques enchaînés par AND
    dedup = re.compile(
        r"(LOWER\(coalesce\([A-Za-z0-9_\.]*?campaign_type,''\)\) NOT LIKE '%brand%')"
        r"(\s+AND\s+\1)+")
    prev = None
    while prev != out:
        prev = out
        out = dedup.sub(r"\1", out)
    # 4. étend chaque atome type en paire canonique (catégorie stricte)
    pair = re.compile(r"LOWER\(coalesce\(([A-Za-z0-9_\.]*?)campaign_type,''\)\) NOT LIKE '%brand%'")
    return pair.sub(
        lambda m: (f"LOWER(coalesce({m.group(1)}campaign_type,'')) NOT LIKE '%brand%' "
                   f"AND LOWER(TRIM(coalesce({m.group(1)}campaign_category,''))) != 'brand'"),
        out)

def displayed_cells(cols, rows, metrics):
    """Cellules numériques triées/arrondies (convention card_values), restreintes
    aux colonnes `metrics` (insensible à la casse) ; toutes si metrics est None."""
    if metrics is None:
        keep = set(range(len(cols)))
    else:
        wanted = {str(m).upper() for m in metrics}
        keep = {i for i, c in enumerate(cols) if str(c).upper() in wanted}
    return sorted(round(float(x), 4) for row in rows for i, x in enumerate(row)
                  if i in keep and isinstance(x, (int, float)))

def kpi_signature(card):
    """The SET of metric KINDS the card displays. For real charts use graph.metrics
    (reliable); for single-value displays graph.metrics is leftover/unreliable, so fall
    back to the headline metric from the name."""
    display = (card.get("display") or "").lower()
    metrics = (card.get("visualization_settings") or {}).get("graph.metrics")
    if display not in _SCALAR_DISPLAYS and metrics:
        kinds = {series_kind(m) for m in metrics if isinstance(m, str)}
        if kinds:
            return tuple(sorted(kinds))
    return (metric_kind(card.get("name")),)

def brand_excluded(card):
    """True if the card is a hardcoded 'without brand' / 'brand excluded' variant.
    The new tree names these explicitly; old cards instead use the brand_included filter."""
    n = (card.get("name") or "").lower()
    return ("without brand" in n) or ("brand exclud" in n) or ("brand_exclud" in n)

def _old_slots_and_value(card):
    """(sorted distinct slots, is_value) inferred from the old columns the card sums.
    Returns ([], False) if the card references no old conversion column."""
    sql, _ = native_and_tags(card)
    cols = old_conversion_columns(sql)
    if not cols:
        return [], False
    is_value = any(c.endswith("_VALUE") for c in cols)
    slots = set()
    for c in cols:
        if c in ("CONVERSIONS", "CONVERSION_VALUE"):
            slots.add(0)
        else:
            mm = re.search(r"(\d+)", c)
            if mm:
                slots.add(int(mm.group(1)))
    return sorted(slots), is_value

def resolve_new_card(old_card, client_mapping, new_index):
    """Return {status: ok|unmapped|conflict|multi|review|skip, ...}. The `ok` result
    carries old_col + new_col + source so the caller can reconcile without recomputing.

    new_index maps (NEW_COL, breakdown) -> [{id, source, display, kpis, brand}]. A candidate
    is eligible iff it has the SAME source table, the SAME displayed-KPI set, and the SAME
    brand-exclusion flag as the old card. Chart type is allowed to differ (bar->combo); when
    several remain, prefer the same display, else it's a genuine `multi`."""
    sql, _ = native_and_tags(old_card)
    slots, is_value = _old_slots_and_value(old_card)
    if not slots:
        return {"status": "skip", "reason": "no old conversion column"}
    if len(slots) > 1:
        return {"status": "review", "reason": f"multi-slot combo {slots}", "slots": slots}
    source = conversion_source(sql)
    slot = slots[0]
    nt = client_mapping.get(slot)
    if nt is None:
        return {"status": "review", "reason": f"slot {slot} absent from client mapping", "source": source}
    if nt in (UNMAPPED, CONFLICT):
        return {"status": nt.strip("_").lower(), "slot": slot, "source": source}
    count_col, value_col = new_type_columns(nt)
    new_col = value_col if is_value else count_col
    old_col = slot_old_columns(slot)[1 if is_value else 0]
    base = {"new_type": nt, "old_col": old_col, "new_col": new_col, "slot": slot, "source": source}
    if not new_col:
        return {"status": "review", **base,
                "reason": f"new_type {nt!r} has no {'value' if is_value else 'count'} column"}
    bd = card_breakdown(old_card)
    kpis, brand, disp = kpi_signature(old_card), brand_excluded(old_card), (old_card.get("display") or "")
    all_cands = new_index.get((new_col, bd)) or []
    same_src = [c for c in all_cands if c.get("source") == source]
    match = [c for c in same_src if tuple(c.get("kpis") or ()) == kpis and bool(c.get("brand")) == brand]
    if len(match) > 1:  # several true matches -> prefer same chart type
        sd = [c for c in match if c.get("display") == disp]
        if len(sd) == 1:
            match = sd
    if len(match) == 1:
        return {"status": "ok", "new_card_id": match[0]["id"], **base}
    if len(match) > 1:
        return {"status": "multi", "candidates": [c["id"] for c in match], **base}
    if same_src:
        return {"status": "review", **base,
                "reason": f"no KPI/brand match for {new_col} kpis={list(kpis)} brand={brand} "
                          f"(same-source candidates: {[c['id'] for c in same_src][:6]})"}
    if all_cands:
        return {"status": "review", **base,
                "reason": f"no new card on source {source!r} (other-source: {[c['id'] for c in all_cands][:5]})"}
    return {"status": "review", **base, "reason": f"no new card for {new_col} breakdown {list(bd)}"}
