# Card Naming Normalization — Phase 1.5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire un outil CLI qui normalise en live les noms des ~1 212 cartes de la collection Metabase 215 (hors `Nouvelles Conversions`) — règles déterministes pour les corrections mécaniques, gate de relecture humaine sur les décisions, snapshot/verify/rollback comme filet.

**Architecture:** Deux fichiers Python sous `scripts/`, indépendants de l'outil Phase 1. `rename_lib.py` contient toute la logique pure (`normalize_name`, modèle d'état, génération de la proposition, vérification d'invariant) — testée unitairement. `rename_phase15.py` est le CLI : il lit `.env`, appelle l'API Metabase via la librairie `spark_metabase_api`, orchestre `snapshot · propose · apply · verify · rollback`. L'artefact de relecture est un CSV éditable (`migration/rename-proposal.csv`).

**Tech Stack:** Python 3, `spark_metabase_api`, modules stdlib (`csv`, `re`, `dataclasses`, `pathlib`).

**Spec de référence :** `docs/superpowers/specs/2026-05-21-card-naming-normalization-phase1.5-design.md`.

---

## Convention de test

Comme pour la Phase 1, on ne dépend d'aucun framework (`pip` PEP 668 + convention du repo).
`tests/test_rename_lib.py` est un script autonome lancé par
**`python3 tests/test_rename_lib.py`**, qui exécute toutes ses fonctions `test_*` et sort
en code ≠ 0 si l'une échoue. Pattern identique à `tests/test_reorg_lib.py`.

## File Structure

| Fichier | Responsabilité |
|---|---|
| `scripts/rename_lib.py` | Logique pure : constantes (acronymes, libellés viz, patterns cryptiques), `CardRecord`, `Snapshot`, `normalize_name`, `propose_renames`, `verify_invariant`. Aucun effet de bord. |
| `scripts/rename_phase15.py` | CLI : argparse, `.env`, connexion Metabase, `snapshot/propose/apply/verify/rollback`. Importe `rename_lib`. |
| `tests/test_rename_lib.py` | Tests unitaires de toute la logique pure. |
| `migration/rename-snapshot-<ts>.json` | Snapshot pré-vol (généré au runtime). Gitignoré comme les snapshots Phase 1. |
| `migration/rename-proposal.csv` | Proposition de renommage (générée, éditée par l'utilisateur, relue par `apply`). |

## Constantes partagées

Définies en tête de `scripts/rename_lib.py` :

```python
ROOT_COLLECTION_ID = 215
EXCLUDE_COLLECTION_ID = 11673   # Nouvelles Conversions — non traitée en 1.5

ACRONYMS = {
    "CAC", "CPC", "CPM", "CPL", "CPA", "CPI",
    "CTR", "CR", "ROAS", "COS", "KPI", "KPIs",
    "SEO", "GA4", "PMax", "DPA", "ATC", "ROI",
}

DISPLAY_LABEL = {
    "line": "Line", "bar": "Bar", "area": "Area", "combo": "Combo",
    "pie": "Pie", "table": "Table", "scalar": "Scalar",
    "smartscalar": "Smart scalar", "funnel": "Funnel",
    "map": "Map", "waterfall": "Waterfall", "row": "Row",
    "progress": "Progress", "gauge": "Gauge", "pivot": "Pivot",
}

CRYPTIC_PATTERNS = (r"^Cac\d+$", r"^Conv\d+$")
```

---

## Task 1: Harnais de test + `normalize_name`

**Files:**
- Create: `scripts/rename_lib.py`
- Create: `tests/test_rename_lib.py`

`normalize_name` applique : trim, `_`→espace, doubles espaces collapsés, true
Sentence case (lowercase puis acronymes en majuscule par allowlist, première
lettre du nom en majuscule).

- [ ] **Step 1: Créer `tests/test_rename_lib.py` avec le harnais et le premier test**

```python
#!/usr/bin/env python3
"""Tests unitaires de rename_lib — script autonome (convention du repo).

Usage : python3 tests/test_rename_lib.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from rename_lib import normalize_name


def test_normalize_name_basic():
    # Trim + doubles espaces + snake_case
    assert normalize_name("  Add_to_cart_rate ") == "Add to cart rate"
    assert normalize_name("Cac_7,  conversions_7 by date") == "CAC 7, conversions 7 by date"
    # Acronymes préservés
    assert normalize_name("cac") == "CAC"
    assert normalize_name("Cpc by date") == "CPC by date"
    assert normalize_name("CAC") == "CAC"
    # Sentence case + première lettre capitalisée
    assert normalize_name("average basket - purchase") == "Average basket - purchase"
    # Idempotence
    assert normalize_name(normalize_name("App_installs_rate")) == normalize_name("App_installs_rate")
    # Vide / blanc
    assert normalize_name("   ") == ""


TESTS = [test_normalize_name_basic]


def run():
    failures = 0
    for t in TESTS:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failures += 1
            print(f"FAIL  {t.__name__}: {e!r}")
    print(f"\n{len(TESTS) - failures}/{len(TESTS)} tests passés")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    run()
```

Chaque tâche suivante **ajoute** sa fonction `test_*` et l'inscrit dans `TESTS`.

- [ ] **Step 2: Lancer, voir échouer**

Run: `python3 tests/test_rename_lib.py`
Expected: `ModuleNotFoundError: No module named 'rename_lib'`.

- [ ] **Step 3: Implémenter `normalize_name` dans `scripts/rename_lib.py`**

```python
"""Logique pure de la Phase 1.5 — normalisation du nommage des cartes."""
from __future__ import annotations

import re
from dataclasses import dataclass

ROOT_COLLECTION_ID = 215
EXCLUDE_COLLECTION_ID = 11673

ACRONYMS = {
    "CAC", "CPC", "CPM", "CPL", "CPA", "CPI",
    "CTR", "CR", "ROAS", "COS", "KPI", "KPIs",
    "SEO", "GA4", "PMax", "DPA", "ATC", "ROI",
}

_ACRONYM_BY_UPPER = {a.upper(): a for a in ACRONYMS}
_TOKEN_RE = re.compile(r"^(\W*)([A-Za-z0-9]+)(\W*)$")


def _fix_acronym(tok: str) -> str:
    m = _TOKEN_RE.match(tok)
    if not m:
        return tok
    pre, core, post = m.groups()
    canonical = _ACRONYM_BY_UPPER.get(core.upper())
    return f"{pre}{canonical}{post}" if canonical else tok


def normalize_name(name: str) -> str:
    """Trim, snake_case→spaces, Sentence case, acronymes préservés."""
    s = name.replace("_", " ").strip()
    s = re.sub(r"\s+", " ", s)
    if not s:
        return s
    s = s.lower()
    s = " ".join(_fix_acronym(t) for t in s.split(" "))
    # Capitaliser le premier caractère alphabétique
    for i, ch in enumerate(s):
        if ch.isalpha():
            return s[:i] + ch.upper() + s[i + 1 :]
    return s
```

- [ ] **Step 4: Lancer, vérifier que le test passe**

Run: `python3 tests/test_rename_lib.py`
Expected: `PASS  test_normalize_name_basic` ; `1/1 tests passés`.

- [ ] **Step 5: Commit**

```bash
git add scripts/rename_lib.py tests/test_rename_lib.py
git commit -m "rename: normalize_name + harnais de test"
```

---

## Task 2: Modèle `CardRecord` + capture d'état

**Files:**
- Modify: `scripts/rename_lib.py`
- Modify: `tests/test_rename_lib.py`

Capture les cartes du sous-arbre 215 hors `Nouvelles Conversions`, en incluant
le champ **`display`** (nécessaire pour la disambiguïsation viz par collision).

- [ ] **Step 1: Ajouter le test de `capture_snapshot` avec un faux client**

Dans `tests/test_rename_lib.py`, mettre à jour l'import et ajouter le test :

```python
from rename_lib import normalize_name, CardRecord, capture_snapshot


def test_capture_snapshot_excludes_conversions():
    items = {
        "/api/collection/215/items?limit=2000": {"data": [
            {"model": "collection", "id": 214, "name": "Cross-platform"},
            {"model": "collection", "id": 11673, "name": "18. Nouvelles Conversions"},
            {"model": "card", "id": 29, "name": "CAC"},
        ]},
        "/api/collection/214/items?limit=2000": {"data": [
            {"model": "card", "id": 46255, "name": "Loose card"},
        ]},
    }
    cards = {
        29: {"id": 29, "name": "CAC", "collection_id": 215,
             "dashboard_count": 1211, "archived": False, "display": "scalar"},
        46255: {"id": 46255, "name": "Loose card", "collection_id": 214,
                "dashboard_count": 0, "archived": False, "display": "line"},
    }

    def fake_get(endpoint):
        if "/items" in endpoint:
            return items[endpoint]
        card_id = int(endpoint.split("/")[-1])
        return cards[card_id]

    snap = capture_snapshot(fake_get, root_id=215)
    assert set(snap) == {29, 46255}
    assert snap[29] == CardRecord(id=29, name="CAC", collection_id=215,
                                  dashboard_count=1211, archived=False,
                                  display="scalar")
```

Et ajouter `test_capture_snapshot_excludes_conversions` à `TESTS`.

- [ ] **Step 2: Lancer, voir échouer**

Run: `python3 tests/test_rename_lib.py`
Expected: `ImportError: cannot import name 'CardRecord'`.

- [ ] **Step 3: Implémenter `CardRecord` et `capture_snapshot`**

À ajouter à `scripts/rename_lib.py` :

```python
@dataclass(frozen=True)
class CardRecord:
    id: int
    name: str
    collection_id: int
    dashboard_count: int
    archived: bool
    display: str


def capture_snapshot(get, root_id: int = ROOT_COLLECTION_ID) -> dict[int, CardRecord]:
    """Parcourt le sous-arbre `root_id` et capture les cartes (hors EXCLUDE).

    `get` est une fonction `endpoint -> json`. Le sous-arbre
    EXCLUDE_COLLECTION_ID n'est pas parcouru.
    """
    cards: dict[int, CardRecord] = {}

    def walk(coll_id: int):
        items = get(f"/api/collection/{coll_id}/items?limit=2000").get("data", [])
        for it in items:
            if it["model"] == "collection":
                if it["id"] != EXCLUDE_COLLECTION_ID:
                    walk(it["id"])
            elif it["model"] in ("card", "dataset"):
                detail = get(f"/api/card/{it['id']}")
                cards[it["id"]] = CardRecord(
                    id=detail["id"],
                    name=detail["name"],
                    collection_id=detail.get("collection_id"),
                    dashboard_count=detail.get("dashboard_count", 0),
                    archived=bool(detail.get("archived", False)),
                    display=detail.get("display") or "",
                )

    walk(root_id)
    return cards
```

- [ ] **Step 4: Lancer, vérifier le pass**

Run: `python3 tests/test_rename_lib.py`
Expected: 2/2 tests passés.

- [ ] **Step 5: Commit**

```bash
git add scripts/rename_lib.py tests/test_rename_lib.py
git commit -m "rename: CardRecord + capture_snapshot avec champ display"
```

---

## Task 3: Génération de la proposition (`propose_renames`)

**Files:**
- Modify: `scripts/rename_lib.py`
- Modify: `tests/test_rename_lib.py`

Algorithme :

1. Pour chaque carte : `normalized = normalize_name(name)`.
2. Grouper par `normalized`.
3. Pour chaque groupe :
   - **Singleton** : si `normalized != current` → `ProposalRow(status='auto', rule='normalize')`.
   - **Multi avec displays tous distincts** : suffixer chaque carte ` — <DisplayLabel>` → `status='auto', rule='viz_collision'`.
   - **Multi avec ≥ 2 cartes du même `display`** : tout le groupe en `status='décision'`, `rule='duplicate'`, `proposed_name=current_name` (le humain tranche).
4. Marquer en `status='décision'` les cartes dont le `current_name` (ou normalized) matche `CRYPTIC_PATTERNS`, avec `rule='cryptic'`.
5. Ne retenir que les lignes où `(proposed_name != current_name) or (status == 'décision')`.

- [ ] **Step 1: Ajouter les tests de `propose_renames`**

Ajouter à `tests/test_rename_lib.py` (et à `TESTS`) :

```python
from rename_lib import propose_renames, ProposalRow


def _rec(id, name, display="line", collection_id=214, dashboard_count=0):
    return CardRecord(id=id, name=name, collection_id=collection_id,
                      dashboard_count=dashboard_count, archived=False,
                      display=display)


def test_propose_skips_unchanged_cards():
    snap = {1: _rec(1, "Add to cart rate")}     # déjà propre
    rows = propose_renames(snap)
    assert rows == []


def test_propose_auto_normalize_change():
    snap = {1: _rec(1, "Add_to_cart_rate")}
    rows = propose_renames(snap)
    assert len(rows) == 1
    assert rows[0].card_id == 1
    assert rows[0].proposed_name == "Add to cart rate"
    assert rows[0].status == "auto"
    assert rows[0].rule == "normalize"


def test_propose_viz_collision_adds_suffix():
    snap = {
        1: _rec(1, "Cac by date", display="line"),
        2: _rec(2, "Cac by date", display="bar"),
    }
    rows = sorted(propose_renames(snap), key=lambda r: r.card_id)
    assert [r.proposed_name for r in rows] == ["CAC by date — Line", "CAC by date — Bar"]
    assert [r.status for r in rows] == ["auto", "auto"]
    assert [r.rule for r in rows] == ["viz_collision", "viz_collision"]


def test_propose_true_duplicate_is_decision():
    snap = {
        1: _rec(1, "Cac_2 by date, channel", display="line"),
        2: _rec(2, "Cac_2 by date, channel", display="line"),
    }
    rows = sorted(propose_renames(snap), key=lambda r: r.card_id)
    assert [r.status for r in rows] == ["décision", "décision"]
    assert [r.rule for r in rows] == ["duplicate", "duplicate"]
    # En statut décision, on laisse proposed = current
    assert rows[0].proposed_name == rows[0].current_name


def test_propose_cryptic_is_decision():
    snap = {1: _rec(1, "Cac3")}
    rows = propose_renames(snap)
    assert len(rows) == 1
    assert rows[0].status == "décision"
    assert rows[0].rule == "cryptic"
    assert rows[0].proposed_name == "Cac3"
```

- [ ] **Step 2: Lancer, voir échouer**

Run: `python3 tests/test_rename_lib.py`
Expected: `ImportError: cannot import name 'propose_renames'`.

- [ ] **Step 3: Implémenter `ProposalRow` et `propose_renames`**

À ajouter à `scripts/rename_lib.py` :

```python
from collections import defaultdict


DISPLAY_LABEL = {
    "line": "Line", "bar": "Bar", "area": "Area", "combo": "Combo",
    "pie": "Pie", "table": "Table", "scalar": "Scalar",
    "smartscalar": "Smart scalar", "funnel": "Funnel",
    "map": "Map", "waterfall": "Waterfall", "row": "Row",
    "progress": "Progress", "gauge": "Gauge", "pivot": "Pivot",
}

_CRYPTIC = [re.compile(p) for p in (r"^Cac\d+$", r"^Conv\d+$")]


@dataclass(frozen=True)
class ProposalRow:
    card_id: int
    current_name: str
    proposed_name: str
    rule: str        # normalize | viz_collision | duplicate | cryptic
    status: str      # auto | décision
    notes: str = ""


def _is_cryptic(name: str) -> bool:
    return any(p.match(name) for p in _CRYPTIC)


def _viz_label(display: str) -> str:
    return DISPLAY_LABEL.get(display, display.title() if display else "?")


def propose_renames(snapshot: dict[int, CardRecord]) -> list[ProposalRow]:
    # Group by normalized name
    groups: dict[str, list[CardRecord]] = defaultdict(list)
    for rec in snapshot.values():
        groups[normalize_name(rec.name)].append(rec)

    rows: list[ProposalRow] = []
    for normalized, members in groups.items():
        if len(members) == 1:
            rec = members[0]
            if _is_cryptic(rec.name):
                rows.append(ProposalRow(
                    card_id=rec.id, current_name=rec.name,
                    proposed_name=rec.name, rule="cryptic", status="décision",
                    notes="nom court non descriptif — humain décide"))
            elif normalized != rec.name:
                rows.append(ProposalRow(
                    card_id=rec.id, current_name=rec.name,
                    proposed_name=normalized, rule="normalize", status="auto"))
            continue

        # Groupe de 2+ cartes au même nom normalisé
        displays = [m.display for m in members]
        has_dup_display = len(set(displays)) < len(displays)
        if has_dup_display:
            # Au moins 2 cartes partagent le même display -> vrai doublon, humain tranche
            ids = ", ".join(f"#{m.id}" for m in members)
            for rec in members:
                rows.append(ProposalRow(
                    card_id=rec.id, current_name=rec.name,
                    proposed_name=rec.name, rule="duplicate", status="décision",
                    notes=f"doublon dans le groupe ({ids})"))
        else:
            # Tous les displays distincts -> suffixer
            for rec in members:
                proposed = f"{normalized} — {_viz_label(rec.display)}"
                rows.append(ProposalRow(
                    card_id=rec.id, current_name=rec.name,
                    proposed_name=proposed, rule="viz_collision", status="auto"))

    return rows
```

- [ ] **Step 4: Lancer, vérifier les passages**

Run: `python3 tests/test_rename_lib.py`
Expected: 7/7 tests passés.

- [ ] **Step 5: Commit**

```bash
git add scripts/rename_lib.py tests/test_rename_lib.py
git commit -m "rename: propose_renames avec collisions viz et cryptiques"
```

---

## Task 4: Vérification d'invariant

**Files:**
- Modify: `scripts/rename_lib.py`
- Modify: `tests/test_rename_lib.py`

L'invariant Phase 1.5 : même ensemble de cartes, aucune archivée, `dashboard_count`
**ET** `collection_id` strictement identiques au snapshot. Le `name` peut changer
(c'est le but).

- [ ] **Step 1: Ajouter les tests de `verify_invariant`**

```python
from rename_lib import verify_invariant


def test_verify_clean_when_only_name_changed():
    base = {1: _rec(1, "Cac_2", display="line")}
    current = {1: _rec(1, "CAC 2", display="line")}
    assert verify_invariant(base, current) == []


def test_verify_detects_lost_card():
    base = {1: _rec(1, "X")}
    assert [d.kind for d in verify_invariant(base, {})] == ["lost_card"]


def test_verify_detects_archived_card():
    base = {1: _rec(1, "X")}
    archived = CardRecord(1, "X", 214, 0, True, "line")
    assert [d.kind for d in verify_invariant(base, {1: archived})] == ["archived_card"]


def test_verify_detects_dashboard_count_change():
    base = {1: _rec(1, "X", dashboard_count=10)}
    cur = {1: _rec(1, "X", dashboard_count=9)}
    assert [d.kind for d in verify_invariant(base, cur)] == ["dashboard_count_changed"]


def test_verify_detects_moved_card():
    base = {1: _rec(1, "X", collection_id=214)}
    cur = {1: _rec(1, "X", collection_id=999)}
    assert [d.kind for d in verify_invariant(base, cur)] == ["moved_card"]
```

Ajouter les 5 tests à `TESTS`.

- [ ] **Step 2: Lancer, voir échouer**

Run: `python3 tests/test_rename_lib.py`
Expected: `ImportError: cannot import name 'verify_invariant'`.

- [ ] **Step 3: Implémenter `verify_invariant` et `Divergence`**

```python
@dataclass(frozen=True)
class Divergence:
    kind: str        # lost_card | archived_card | dashboard_count_changed | moved_card
    card_id: int
    detail: str


def verify_invariant(baseline: dict[int, CardRecord],
                     current: dict[int, CardRecord]) -> list[Divergence]:
    out: list[Divergence] = []
    for cid, base in baseline.items():
        cur = current.get(cid)
        if cur is None:
            out.append(Divergence("lost_card", cid,
                                   f"{base.name!r} absente de l'état courant"))
            continue
        if cur.archived and not base.archived:
            out.append(Divergence("archived_card", cid,
                                   f"{base.name!r} a été archivée"))
        if cur.dashboard_count != base.dashboard_count:
            out.append(Divergence(
                "dashboard_count_changed", cid,
                f"{base.name!r}: dashboard_count "
                f"{base.dashboard_count} -> {cur.dashboard_count}"))
        if cur.collection_id != base.collection_id:
            out.append(Divergence(
                "moved_card", cid,
                f"{base.name!r}: collection {base.collection_id} -> "
                f"{cur.collection_id}"))
    return out
```

- [ ] **Step 4: Lancer, vérifier les passages**

Run: `python3 tests/test_rename_lib.py`
Expected: 12/12 tests passés.

- [ ] **Step 5: Commit**

```bash
git add scripts/rename_lib.py tests/test_rename_lib.py
git commit -m "rename: invariant (lost/archived/moved/dashboard_count) pour le renommage"
```

---

## Task 5: Squelette du CLI et commande `snapshot`

**Files:**
- Create: `scripts/rename_phase15.py`

- [ ] **Step 1: Créer le squelette + `cmd_snapshot`**

```python
#!/usr/bin/env python3
"""CLI de normalisation des noms de cartes — collection Metabase 215.

Sous-commandes : snapshot | propose | apply | verify | rollback.
Voir docs/superpowers/specs/2026-05-21-card-naming-normalization-phase1.5-design.md
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

from spark_metabase_api import Metabase_API  # noqa: E402
from rename_lib import (  # noqa: E402
    capture_snapshot, propose_renames, verify_invariant,
    CardRecord, ROOT_COLLECTION_ID,
)

MIGRATION_DIR = REPO_ROOT / "migration"


def _load_env() -> dict:
    env = {}
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def connect() -> Metabase_API:
    env = _load_env()
    domain = env.get("METABASE_DOMAIN") or os.environ.get("METABASE_DOMAIN")
    session_id = env.get("METABASE_SESSION_ID") or os.environ.get("METABASE_SESSION_ID")
    email = env.get("METABASE_EMAIL") or os.environ.get("METABASE_EMAIL")
    password = env.get("METABASE_PASSWORD") or os.environ.get("METABASE_PASSWORD")
    if not domain:
        sys.exit("METABASE_DOMAIN manquant.")
    if session_id:
        mb = Metabase_API(domain=domain, session_id=session_id)
        if mb.is_session_valid():
            return mb
        print("session_id expiré — bascule sur email/password.")
    if not (email and password):
        sys.exit("Aucune session valide et METABASE_EMAIL/PASSWORD manquants.")
    return Metabase_API(domain=domain, email=email, password=password)


def _snapshot_to_dict(snap: dict[int, CardRecord]) -> dict:
    return {"cards": [asdict(r) for r in snap.values()]}


def _snapshot_from_dict(data: dict) -> dict[int, CardRecord]:
    return {c["id"]: CardRecord(**c) for c in data["cards"]}


def cmd_snapshot(args):
    mb = connect()
    print(f"Capture du sous-arbre de la collection {ROOT_COLLECTION_ID} "
          f"(hors Nouvelles Conversions)...")
    snap = capture_snapshot(mb.get, root_id=ROOT_COLLECTION_ID)
    MIGRATION_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = MIGRATION_DIR / f"rename-snapshot-{ts}.json"
    out.write_text(json.dumps(_snapshot_to_dict(snap), indent=2, ensure_ascii=False))
    print(f"  {len(snap)} cartes capturées")
    print(f"Snapshot écrit : {out}")


def cmd_propose(args):
    raise NotImplementedError


def cmd_apply(args):
    raise NotImplementedError


def cmd_verify(args):
    raise NotImplementedError


def cmd_rollback(args):
    raise NotImplementedError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Normalisation des noms — Phase 1.5")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("snapshot", help="Capturer l'état des cartes du sous-arbre 215")

    p_prop = sub.add_parser("propose", help="Générer rename-proposal.csv")
    p_prop.add_argument("--snapshot", required=True)
    p_prop.add_argument("--out", default=str(MIGRATION_DIR / "rename-proposal.csv"))

    p_apply = sub.add_parser("apply", help="Appliquer le CSV de renommage")
    p_apply.add_argument("--snapshot", required=True)
    p_apply.add_argument("--proposal", default=str(MIGRATION_DIR / "rename-proposal.csv"))
    p_apply.add_argument("--yes", action="store_true")

    p_verify = sub.add_parser("verify", help="Comparer l'état live au snapshot")
    p_verify.add_argument("--snapshot", required=True)

    p_rb = sub.add_parser("rollback", help="Restaurer les noms d'origine")
    p_rb.add_argument("--snapshot", required=True)
    p_rb.add_argument("--yes", action="store_true")

    args = parser.parse_args(argv)
    {"snapshot": cmd_snapshot, "propose": cmd_propose, "apply": cmd_apply,
     "verify": cmd_verify, "rollback": cmd_rollback}[args.command](args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Vérifier l'aide du CLI**

Run: `python3 scripts/rename_phase15.py --help`
Expected: liste les 5 sous-commandes.

- [ ] **Step 3: Lancer le snapshot live (lecture seule)**

Run: `python3 scripts/rename_phase15.py snapshot`
Expected: ~1 212 cartes capturées ; nouveau fichier `migration/rename-snapshot-<ts>.json`.
Durée : quelques minutes (1 GET par carte).

- [ ] **Step 4: Commit**

```bash
git add scripts/rename_phase15.py
git commit -m "rename: squelette CLI + commande snapshot"
```

---

## Task 6: Commande `propose` (génération du CSV)

**Files:**
- Modify: `scripts/rename_phase15.py`

Le CSV contient toutes les lignes où il y a quelque chose à faire (changement
mécanique OU statut `décision`). Trié par statut (décisions d'abord) puis
par nom courant, pour faciliter la relecture.

- [ ] **Step 1: Implémenter `cmd_propose`**

Remplacer `cmd_propose` dans `scripts/rename_phase15.py` :

```python
def cmd_propose(args):
    snap = _snapshot_from_dict(json.loads(Path(args.snapshot).read_text()))
    rows = propose_renames(snap)
    # Tri : décisions d'abord, puis par nom courant
    rows.sort(key=lambda r: (0 if r.status == "décision" else 1, r.current_name))
    out = Path(args.out)
    out.parent.mkdir(exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["card_id", "current_name", "proposed_name",
                    "rule", "status", "notes"])
        for r in rows:
            w.writerow([r.card_id, r.current_name, r.proposed_name,
                        r.rule, r.status, r.notes])
    by_status = {"auto": 0, "décision": 0}
    by_rule: dict[str, int] = {}
    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        by_rule[r.rule] = by_rule.get(r.rule, 0) + 1
    print(f"Proposition écrite : {out}")
    print(f"  {len(rows)} lignes — auto: {by_status['auto']}, "
          f"décision: {by_status['décision']}")
    print(f"  par règle : " + ", ".join(f"{k}={v}" for k, v in sorted(by_rule.items())))
    print("\n→ Relis et édite le CSV avant `apply`.")
```

- [ ] **Step 2: Lancer la proposition contre le snapshot live**

Run: `SNAP=$(ls migration/rename-snapshot-*.json | tail -1); python3 scripts/rename_phase15.py propose --snapshot "$SNAP"`
Expected: création de `migration/rename-proposal.csv` ; résumé imprimé (compte
auto vs décision, ventilation par règle).

- [ ] **Step 3: Inspecter le CSV (qualitatif)**

Run: `head -20 migration/rename-proposal.csv && echo "---" && wc -l migration/rename-proposal.csv`
Expected: en-tête + lignes lisibles, lignes `décision` en haut.

- [ ] **Step 4: Commit**

```bash
git add scripts/rename_phase15.py
git commit -m "rename: commande propose (CSV de relecture)"
```

---

## Task 7: Commande `apply` avec vérification post-batch

**Files:**
- Modify: `scripts/rename_phase15.py`

`apply` lit le CSV, applique uniquement les lignes où `proposed_name != current_name`
et `proposed_name` est non vide. Chaque PUT contrôlé par code HTTP. Vérification
post-batch contre le snapshot baseline.

- [ ] **Step 1: Implémenter `_check` et `cmd_apply`**

Ajouter à `scripts/rename_phase15.py` :

```python
def _check(status, what):
    """`mb.put` renvoie un code HTTP — on échoue fort si non-2xx."""
    if not (200 <= int(status) < 300):
        raise RuntimeError(f"{what} a échoué — HTTP {status}")


def _load_proposal(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def cmd_apply(args):
    baseline = _snapshot_from_dict(json.loads(Path(args.snapshot).read_text()))
    proposal = _load_proposal(Path(args.proposal))
    # Filtrer : ne renommer que les lignes où proposed != current ET proposed non vide
    to_apply = [r for r in proposal
                if r["proposed_name"] and r["proposed_name"] != r["current_name"]]
    if not to_apply:
        print("Aucun renommage à appliquer.")
        return

    print(f"\n=== Renommages à appliquer : {len(to_apply)} ===")
    for r in to_apply[:20]:
        print(f"  #{r['card_id']:>6} : {r['current_name']!r} -> {r['proposed_name']!r}  "
              f"[{r['rule']}/{r['status']}]")
    if len(to_apply) > 20:
        print(f"  ... ({len(to_apply) - 20} de plus)")
    if not args.yes:
        if input(f"\nAppliquer ces {len(to_apply)} renommages ? [tape 'oui'] "
                 ).strip() != "oui":
            sys.exit("Annulé.")

    mb = connect()
    for r in to_apply:
        cid = int(r["card_id"])
        new_name = r["proposed_name"]
        _check(mb.put(f"/api/card/{cid}", json={"name": new_name}),
               f"renommage carte {cid}")
        print(f"  #{cid} -> {new_name!r}")

    print("\nVérification d'invariant post-batch...")
    current = capture_snapshot(mb.get, root_id=ROOT_COLLECTION_ID)
    divergences = verify_invariant(baseline, current)
    if divergences:
        print("DIVERGENCES DÉTECTÉES — ARRÊT :")
        for d in divergences:
            print(f"  [{d.kind}] carte {d.card_id} : {d.detail}")
        sys.exit(1)
    print(f"OK — {len(current)} cartes intactes (hors changement de nom), "
          f"0 divergence.")
```

- [ ] **Step 2: Vérifier que `apply` refuse sans confirmation (dry-run de garde-fou)**

Run: `SNAP=$(ls migration/rename-snapshot-*.json | tail -1); echo "non" | python3 scripts/rename_phase15.py apply --snapshot "$SNAP"`
Expected: « Annulé. » sans appel d'écriture (sortie code 1).

- [ ] **Step 3: Commit**

```bash
git add scripts/rename_phase15.py
git commit -m "rename: commande apply avec vérification d'invariant post-batch"
```

---

## Task 8: Commandes `verify` et `rollback`

**Files:**
- Modify: `scripts/rename_phase15.py`

- [ ] **Step 1: Implémenter `cmd_verify` et `cmd_rollback`**

Remplacer les deux fonctions :

```python
def cmd_verify(args):
    baseline = _snapshot_from_dict(json.loads(Path(args.snapshot).read_text()))
    mb = connect()
    current = capture_snapshot(mb.get, root_id=ROOT_COLLECTION_ID)
    divergences = verify_invariant(baseline, current)
    if divergences:
        print(f"{len(divergences)} divergence(s) :")
        for d in divergences:
            print(f"  [{d.kind}] carte {d.card_id} : {d.detail}")
        sys.exit(1)
    print(f"OK — {len(current)} cartes, 0 divergence vs snapshot.")


def cmd_rollback(args):
    baseline = _snapshot_from_dict(json.loads(Path(args.snapshot).read_text()))
    if not args.yes:
        if input("Restaurer tous les noms du snapshot ? [tape 'oui'] "
                 ).strip() != "oui":
            sys.exit("Annulé.")
    mb = connect()
    current = capture_snapshot(mb.get, root_id=ROOT_COLLECTION_ID)
    restored = 0
    for cid, base in baseline.items():
        cur = current.get(cid)
        if cur and cur.name != base.name:
            _check(mb.put(f"/api/card/{cid}", json={"name": base.name}),
                   f"restauration carte {cid}")
            print(f"  carte {cid} -> nom d'origine {base.name!r}")
            restored += 1
    print(f"Rollback terminé. {restored} carte(s) restaurée(s).")
```

- [ ] **Step 2: Vérifier `verify` contre le snapshot (état non modifié)**

Run: `SNAP=$(ls migration/rename-snapshot-*.json | tail -1); python3 scripts/rename_phase15.py verify --snapshot "$SNAP"`
Expected: « OK — ~1212 cartes, 0 divergence vs snapshot. »

- [ ] **Step 3: Lancer toute la suite de tests**

Run: `python3 tests/test_rename_lib.py`
Expected: 12/12 tests passés.

- [ ] **Step 4: Commit**

```bash
git add scripts/rename_phase15.py
git commit -m "rename: commandes verify et rollback"
```

---

## Task 9: Gitignore des artefacts runtime + validation end-to-end

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Ajouter le snapshot Phase 1.5 au .gitignore**

Éditer `.gitignore` pour ajouter la ligne sous le bloc « Migration Phase 1 » :

```
# Migration Phase 1 — artefacts runtime (régénérables)
migration/snapshot-*.json
migration/families.json
migration/rename-snapshot-*.json
```

Note : `migration/rename-proposal.csv` reste trackable — c'est le registre de
ce qui a été (ou sera) renommé, on peut le commiter une fois la passe terminée.

- [ ] **Step 2: Snapshot frais (si pas déjà fait)**

Run: `python3 scripts/rename_phase15.py snapshot`
Expected: ~1 212 cartes.

- [ ] **Step 3: Proposer**

Run: `SNAP=$(ls migration/rename-snapshot-*.json | tail -1); python3 scripts/rename_phase15.py propose --snapshot "$SNAP"`
Expected: CSV créé, résumé imprimé. Inspecter la ventilation (auto vs décision).

- [ ] **Step 4: Vérifier l'idempotence par auto-relecture du CSV**

Toute ligne d'`auto` doit produire un `proposed_name` qui, repassé dans
`normalize_name`, donne le même résultat :

```bash
python3 - <<'EOF'
import csv, sys
sys.path.insert(0, 'scripts')
from rename_lib import normalize_name
rows = list(csv.DictReader(open('migration/rename-proposal.csv', encoding='utf-8')))
bad = []
for r in rows:
    if r['status'] != 'auto' or r['rule'] != 'normalize':
        continue
    if normalize_name(r['proposed_name']) != r['proposed_name']:
        bad.append((r['card_id'], r['proposed_name'], normalize_name(r['proposed_name'])))
print(f"{len(rows)} lignes total ; idempotence : {len(bad)} violations")
for b in bad[:5]:
    print(" ", b)
EOF
```
Expected: `0 violations`.

- [ ] **Step 5: Verify idempotent**

Run: `SNAP=$(ls migration/rename-snapshot-*.json | tail -1); python3 scripts/rename_phase15.py verify --snapshot "$SNAP"`
Expected: 0 divergence.

- [ ] **Step 6: Commit du .gitignore**

```bash
git add .gitignore
git commit -m "rename: ignorer les snapshots Phase 1.5"
```

---

## Runbook d'exécution (NON auto-exécutable — gates humains)

Comme pour la Phase 1, ces étapes effectuent les renommages live avec des
validations humaines. Menées **interactivement** avec l'utilisateur.

1. **Snapshot baseline** — `python3 scripts/rename_phase15.py snapshot`.
2. **Génération de la proposition** — `python3 scripts/rename_phase15.py propose --snapshot <snap>`.
3. **GATE — relecture humaine du CSV** : édition de `migration/rename-proposal.csv` :
   - Vérifier la ventilation `auto` / `décision`.
   - Pour chaque ligne `décision` (cryptiques, doublons réels) : remplir
     `proposed_name` (ou laisser = `current_name` pour ne rien changer).
   - Possibilité d'auditer la casse obtenue après acronymes : enrichir la liste
     blanche `ACRONYMS` dans `rename_lib.py` si une lacune apparaît et regénérer.
4. **Échantillon de vérification côté client** : tirer 5-10 cartes parmi celles
   qui vont être renommées (notamment celles à fort `dashboard_count`), vérifier
   sur 2-3 dashboards échantillons que le titre affiché ne casse rien (souvent
   override, voir la découverte du design §Découverte clé).
5. **`apply`** — `python3 scripts/rename_phase15.py apply --snapshot <snap>` (confirmation puis verify automatique).
6. **`verify` final** — re-vérification à froid.
7. En cas de divergence : `apply` s'arrête seul ; `rollback --snapshot <snap>`
   restaure les noms d'origine.

---

## Notes de mise en œuvre

- **Stripping de fragments viz existants** (`- Bar Chart`, `(Bar Stack - 100%)`)
  **n'est pas fait** par les règles : risque d'over-stripping de mots à sens
  métier. Ces fragments restent dans le nom ; si la relecture montre un cas
  gênant, le humain édite la ligne `proposed_name` dans le CSV.
- **Casse sentence case stricte** : `Average basket - Purchase` devient
  `Average basket - purchase` (le P de Purchase passe en minuscule). C'est
  délibéré pour avoir une casse uniforme dans toute la bibliothèque. Si une
  ligne est jugée gênante, le humain la corrige dans le CSV.
- **Liste d'acronymes** : à enrichir au besoin lors de la relecture du CSV.
  Modifier `ACRONYMS` dans `rename_lib.py` et regénérer la proposition.
- **`dashboard_count` modifié pendant l'apply** : peut venir d'une édition
  concurrente, pas du script. Si `verify` le signale, investiguer la carte
  concernée.
