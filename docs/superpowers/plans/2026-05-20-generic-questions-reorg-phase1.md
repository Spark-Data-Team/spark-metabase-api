# Generic Questions Reorg — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire un outil CLI qui réorganise en live la collection Metabase 215 (« 2. Generic Questions ») par déplacements seuls, sans casser aucun dashboard client, avec snapshot, dry-run, vérification d'invariant et rollback.

**Architecture:** Deux fichiers Python sous `scripts/`. `reorg_lib.py` contient toute la logique pure (modèle d'état, chargement du plan déclaratif, calcul des lots d'opérations, vérification d'invariant) — testée unitairement. `reorg_phase1.py` est le CLI : il lit `.env`, appelle l'API Metabase via la librairie `spark_metabase_api`, et orchestre les sous-commandes `snapshot` / `plan` / `apply` / `verify` / `rollback`. Le plan déclaratif `migration/phase1-plan.yaml` est la seule source de vérité des opérations.

**Tech Stack:** Python 3, `spark_metabase_api` (librairie du repo), `PyYAML`, `pytest` (tests), `dataclasses`.

**Spec de référence:** `docs/superpowers/specs/2026-05-20-generic-questions-reorg-phase1-design.md` et `docs/generic-questions-reorg.md`.

---

## Périmètre de ce plan

Les **Tâches 1 à 10 construisent et testent l'outil**. La **migration live elle-même**
(générer le plan, dry-run, appliquer les lots) est décrite dans la section
**« Runbook d'exécution »** en fin de document : elle comporte des points de
validation humaine et **ne doit pas être exécutée automatiquement** par un worker.

## File Structure

| Fichier | Responsabilité |
|---|---|
| `scripts/reorg_lib.py` | Logique pure : `MetabaseState`, `CollectionNode`, `CardRef`, `load_plan`, `compute_lots`, `verify_invariant`. Aucun effet de bord, aucun import réseau. |
| `scripts/reorg_phase1.py` | CLI : argparse, lecture `.env`, connexion Metabase, capture d'état live, exécution des lots, rollback. Importe `reorg_lib`. |
| `tests/conftest.py` | Ajoute `scripts/` au `sys.path` pour que les tests importent `reorg_lib`. |
| `tests/test_reorg_lib.py` | Tests unitaires pytest de toute la logique pure. |
| `migration/phase1-plan.yaml` | Plan déclaratif (généré au runbook, relu par l'utilisateur). |
| `migration/snapshot-<ts>.json` | État pré-vol capturé au runtime (baseline + rollback). |
| `migration/families.json` | Map `clé de famille -> id de collection créée`, écrit par `apply lot-1`. |

## Convention de test (adaptation)

Le repo n'utilise aucun framework de test (`tests/integration_test.py` est un script
autonome). `tests/test_reorg_lib.py` suit cette convention : un script lancé par
`python3 tests/test_reorg_lib.py` qui exécute toutes ses fonctions `test_*` et sort
en code ≠ 0 si l'une échoue. Conséquences sur les tâches ci-dessous :

- Toute commande notée `pytest tests/test_reorg_lib.py::<nom>` se lit
  **`python3 tests/test_reorg_lib.py`** (le runner exécute tous les tests ; on
  vérifie la ligne `PASS`/`FAIL` de la fonction concernée).
- Pas de `pytest`, pas de `conftest.py`, pas d'extra `dev` dans `setup.py`.
- La fixture pytest `tmp_path` est remplacée par `tempfile.TemporaryDirectory()`.
- `PyYAML` est déjà disponible (extra `iac` du paquet).

## Constantes partagées

Définies en tête de `scripts/reorg_lib.py`, réutilisées partout :

```python
ROOT_COLLECTION_ID = 215       # "2. Generic Questions"
EXCLUDE_COLLECTION_ID = 11673  # "18. Nouvelles Conversions" — hors périmètre Phase 1
TO_SORT_COLLECTION_ID = 7252   # "To sort"
```

---

## Task 1: Harnais de test + modèle d'état

**Files:**
- Create: `scripts/reorg_lib.py`
- Create: `tests/test_reorg_lib.py`

- [ ] **Step 1: Créer `tests/test_reorg_lib.py` avec le harnais et le premier test**

```python
#!/usr/bin/env python3
"""Tests unitaires de reorg_lib — script autonome (convention du repo).

Usage : python3 tests/test_reorg_lib.py
"""
import sys
import tempfile
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from reorg_lib import CollectionNode, CardRef, MetabaseState


def test_metabase_state_roundtrip():
    state = MetabaseState(
        collections={
            215: CollectionNode(id=215, name="2. Generic Questions", parent_id=None),
            214: CollectionNode(id=214, name="01. Global", parent_id=215),
        },
        cards={
            29: CardRef(id=29, name="CAC", collection_id=214,
                        dashboard_count=1211, archived=False),
        },
    )
    restored = MetabaseState.from_dict(state.to_dict())
    assert restored == state
    assert restored.cards[29].dashboard_count == 1211


TESTS = [test_metabase_state_roundtrip]


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

- [ ] **Step 2: Lancer le test, vérifier qu'il échoue**

Run: `python3 tests/test_reorg_lib.py`
Expected: erreur — `ModuleNotFoundError: No module named 'reorg_lib'`.

- [ ] **Step 3: Implémenter le modèle d'état dans `scripts/reorg_lib.py`**

```python
"""Logique pure de la migration Phase 1 — aucun effet de bord, aucun réseau."""
from __future__ import annotations

from dataclasses import dataclass

ROOT_COLLECTION_ID = 215
EXCLUDE_COLLECTION_ID = 11673
TO_SORT_COLLECTION_ID = 7252


@dataclass(frozen=True)
class CollectionNode:
    id: int
    name: str
    parent_id: int | None


@dataclass(frozen=True)
class CardRef:
    id: int
    name: str
    collection_id: int
    dashboard_count: int
    archived: bool


@dataclass
class MetabaseState:
    collections: dict[int, CollectionNode]
    cards: dict[int, CardRef]

    def to_dict(self) -> dict:
        return {
            "collections": [
                {"id": c.id, "name": c.name, "parent_id": c.parent_id}
                for c in self.collections.values()
            ],
            "cards": [
                {"id": c.id, "name": c.name, "collection_id": c.collection_id,
                 "dashboard_count": c.dashboard_count, "archived": c.archived}
                for c in self.cards.values()
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MetabaseState":
        collections = {
            c["id"]: CollectionNode(id=c["id"], name=c["name"],
                                    parent_id=c["parent_id"])
            for c in data["collections"]
        }
        cards = {
            c["id"]: CardRef(id=c["id"], name=c["name"],
                             collection_id=c["collection_id"],
                             dashboard_count=c["dashboard_count"],
                             archived=c["archived"])
            for c in data["cards"]
        }
        return cls(collections=collections, cards=cards)
```

- [ ] **Step 4: Lancer le test, vérifier qu'il passe**

Run: `python3 tests/test_reorg_lib.py`
Expected: `PASS  test_metabase_state_roundtrip` ; `1/1 tests passés`.

- [ ] **Step 5: Commit**

```bash
git add scripts/reorg_lib.py tests/test_reorg_lib.py
git commit -m "reorg: modèle d'état pour la migration Phase 1"
```

---

## Task 2: Chargement du plan déclaratif

**Files:**
- Modify: `scripts/reorg_lib.py`
- Test: `tests/test_reorg_lib.py`

Le plan YAML a cette forme (exemple minimal) :

```yaml
families:
  - key: ad_platforms
    name: "Ad platforms"
    description: "Questions spécifiques à une plateforme publicitaire"
collection_moves:
  - id: 209
    new_parent: ad_platforms
    new_name: "Google Ads"
card_filing:
  46255: 217      # card_id -> id de la collection de destination
delete_empty:
  - 211           # "04. Microsoft"
```

- [ ] **Step 1: Écrire le test de `load_plan`**

Ajouter dans `tests/test_reorg_lib.py` :

```python
import textwrap
from reorg_lib import load_plan, FamilySpec, CollectionMove


def test_load_plan(tmp_path):
    plan_file = tmp_path / "plan.yaml"
    plan_file.write_text(textwrap.dedent("""
        families:
          - key: ad_platforms
            name: "Ad platforms"
            description: "Plateformes publicitaires"
        collection_moves:
          - id: 209
            new_parent: ad_platforms
            new_name: "Google Ads"
        card_filing:
          46255: 217
        delete_empty:
          - 211
    """))
    plan = load_plan(plan_file)
    assert plan.families == [FamilySpec(key="ad_platforms", name="Ad platforms",
                                        description="Plateformes publicitaires")]
    assert plan.collection_moves == [CollectionMove(id=209, new_parent="ad_platforms",
                                                    new_name="Google Ads")]
    assert plan.card_filing == {46255: 217}
    assert plan.delete_empty == [211]
```

- [ ] **Step 2: Lancer le test, vérifier qu'il échoue**

Run: `pytest tests/test_reorg_lib.py::test_load_plan -v`
Expected: FAIL — `ImportError: cannot import name 'load_plan'`.

- [ ] **Step 3: Implémenter `load_plan` dans `scripts/reorg_lib.py`**

Ajouter en tête : `import yaml` et `from pathlib import Path`. Puis :

```python
@dataclass(frozen=True)
class FamilySpec:
    key: str
    name: str
    description: str = ""


@dataclass(frozen=True)
class CollectionMove:
    id: int
    new_parent: str   # clé de famille, ou "root"
    new_name: str


@dataclass
class Phase1Plan:
    families: list[FamilySpec]
    collection_moves: list[CollectionMove]
    card_filing: dict[int, int]   # card_id -> id collection destination
    delete_empty: list[int]


def load_plan(path) -> Phase1Plan:
    data = yaml.safe_load(Path(path).read_text()) or {}
    families = [FamilySpec(key=f["key"], name=f["name"],
                           description=f.get("description", ""))
                for f in data.get("families", [])]
    moves = [CollectionMove(id=m["id"], new_parent=m["new_parent"],
                            new_name=m["new_name"])
             for m in data.get("collection_moves", [])]
    card_filing = {int(k): int(v) for k, v in (data.get("card_filing") or {}).items()}
    delete_empty = [int(x) for x in data.get("delete_empty", [])]
    return Phase1Plan(families=families, collection_moves=moves,
                      card_filing=card_filing, delete_empty=delete_empty)
```

- [ ] **Step 4: Lancer le test, vérifier qu'il passe**

Run: `pytest tests/test_reorg_lib.py::test_load_plan -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/reorg_lib.py tests/test_reorg_lib.py
git commit -m "reorg: chargement du plan déclaratif phase1-plan.yaml"
```

---

## Task 3: Vérification d'invariant (cœur de sécurité)

**Files:**
- Modify: `scripts/reorg_lib.py`
- Test: `tests/test_reorg_lib.py`

`verify_invariant` compare un état baseline (snapshot) à un état courant et retourne
la liste des divergences interdites. Un **déplacement** de carte (changement de
`collection_id`) n'est PAS une divergence — c'est l'opération attendue. Les
divergences sont : carte perdue, carte archivée, `dashboard_count` modifié.

- [ ] **Step 1: Écrire les tests de `verify_invariant`**

Ajouter dans `tests/test_reorg_lib.py` :

```python
from reorg_lib import verify_invariant, Divergence


def _state(cards):
    return MetabaseState(collections={}, cards={c.id: c for c in cards})


def test_verify_invariant_clean_when_only_moved():
    base = _state([CardRef(29, "CAC", 214, 1211, False)])
    # même carte, collection différente -> déplacement légitime, pas de divergence
    current = _state([CardRef(29, "CAC", 999, 1211, False)])
    assert verify_invariant(base, current) == []


def test_verify_invariant_detects_lost_card():
    base = _state([CardRef(29, "CAC", 214, 1211, False)])
    current = _state([])
    divs = verify_invariant(base, current)
    assert [d.kind for d in divs] == ["lost_card"]
    assert divs[0].card_id == 29


def test_verify_invariant_detects_archived_card():
    base = _state([CardRef(29, "CAC", 214, 1211, False)])
    current = _state([CardRef(29, "CAC", 214, 1211, True)])
    divs = verify_invariant(base, current)
    assert [d.kind for d in divs] == ["archived_card"]


def test_verify_invariant_detects_dashboard_count_change():
    base = _state([CardRef(29, "CAC", 214, 1211, False)])
    current = _state([CardRef(29, "CAC", 214, 1210, False)])
    divs = verify_invariant(base, current)
    assert [d.kind for d in divs] == ["dashboard_count_changed"]
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `pytest tests/test_reorg_lib.py -k verify_invariant -v`
Expected: FAIL — `ImportError: cannot import name 'verify_invariant'`.

- [ ] **Step 3: Implémenter `verify_invariant` dans `scripts/reorg_lib.py`**

```python
@dataclass(frozen=True)
class Divergence:
    kind: str        # "lost_card" | "archived_card" | "dashboard_count_changed"
    card_id: int
    detail: str


def verify_invariant(baseline: MetabaseState,
                     current: MetabaseState) -> list[Divergence]:
    """Retourne les divergences interdites entre l'état baseline et l'état courant.

    Un changement de `collection_id` (déplacement) n'est PAS une divergence.
    """
    out: list[Divergence] = []
    for cid, base in baseline.cards.items():
        cur = current.cards.get(cid)
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
    return out
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

Run: `pytest tests/test_reorg_lib.py -k verify_invariant -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/reorg_lib.py tests/test_reorg_lib.py
git commit -m "reorg: vérification d'invariant de non-régression"
```

---

## Task 4: Calcul des lots d'opérations

**Files:**
- Modify: `scripts/reorg_lib.py`
- Test: `tests/test_reorg_lib.py`

`compute_lots` transforme `(state, plan)` en un dict ordonné `nom de lot -> liste
d'opérations`. Les lots :

- `lot-1` : créer les familles (`create_collection`).
- `lot-2` : déplacer/renommer les collections (`move_collection`).
- `lot-3` : déplacer les cartes dont la collection courante n'est PAS `To sort`.
- `lot-4` : déplacer les cartes dont la collection courante EST `To sort`.
- `lot-5` : supprimer les collections vides (`delete_collection`).

Le `new_parent` d'un `move_collection` est une **clé de famille** ; elle n'est
résolue en id réel que pendant `apply` (les familles n'existent pas avant `lot-1`).
`compute_lots` laisse donc la clé telle quelle dans `Op.payload["new_parent_key"]`.

- [ ] **Step 1: Écrire le test de `compute_lots`**

Ajouter dans `tests/test_reorg_lib.py` :

```python
from reorg_lib import (compute_lots, FamilySpec, CollectionMove, Phase1Plan,
                       TO_SORT_COLLECTION_ID)


def test_compute_lots_groups_operations():
    state = MetabaseState(
        collections={
            209: CollectionNode(209, "02. Google", 215),
            211: CollectionNode(211, "04. Microsoft", 215),
        },
        cards={
            46255: CardRef(46255, "Loose card", 214, 0, False),
            777: CardRef(777, "To-sort card", TO_SORT_COLLECTION_ID, 3, False),
        },
    )
    plan = Phase1Plan(
        families=[FamilySpec("ad_platforms", "Ad platforms")],
        collection_moves=[CollectionMove(209, "ad_platforms", "Google Ads")],
        card_filing={46255: 217, 777: 218},
        delete_empty=[211],
    )
    lots = compute_lots(state, plan)
    assert [op.kind for op in lots["lot-1"]] == ["create_collection"]
    assert [op.kind for op in lots["lot-2"]] == ["move_collection"]
    assert lots["lot-2"][0].payload["new_parent_key"] == "ad_platforms"
    assert [op.payload["card_id"] for op in lots["lot-3"]] == [46255]
    assert [op.payload["card_id"] for op in lots["lot-4"]] == [777]
    assert [op.payload["collection_id"] for op in lots["lot-5"]] == [211]
```

- [ ] **Step 2: Lancer le test, vérifier qu'il échoue**

Run: `pytest tests/test_reorg_lib.py::test_compute_lots_groups_operations -v`
Expected: FAIL — `ImportError: cannot import name 'compute_lots'`.

- [ ] **Step 3: Implémenter `compute_lots` et `Op` dans `scripts/reorg_lib.py`**

```python
@dataclass(frozen=True)
class Op:
    lot: str
    kind: str        # create_collection|move_collection|move_card|delete_collection
    summary: str
    payload: dict


def compute_lots(state: MetabaseState, plan: Phase1Plan) -> dict[str, list[Op]]:
    lots: dict[str, list[Op]] = {f"lot-{i}": [] for i in range(1, 6)}

    for fam in plan.families:
        lots["lot-1"].append(Op(
            "lot-1", "create_collection",
            f"Créer la famille « {fam.name} »",
            {"key": fam.key, "name": fam.name, "description": fam.description}))

    for mv in plan.collection_moves:
        old = state.collections.get(mv.id)
        old_name = old.name if old else f"#{mv.id}"
        lots["lot-2"].append(Op(
            "lot-2", "move_collection",
            f"Déplacer « {old_name} » -> famille « {mv.new_parent} », "
            f"renommer en « {mv.new_name} »",
            {"collection_id": mv.id, "new_parent_key": mv.new_parent,
             "new_name": mv.new_name}))

    for card_id, dest in plan.card_filing.items():
        card = state.cards.get(card_id)
        if card is None:
            raise ValueError(f"card_filing référence une carte inconnue: {card_id}")
        lot = "lot-4" if card.collection_id == TO_SORT_COLLECTION_ID else "lot-3"
        lots[lot].append(Op(
            lot, "move_card",
            f"Déplacer la carte « {card.name} » (#{card_id}) "
            f"de la collection {card.collection_id} vers {dest}",
            {"card_id": card_id, "collection_id": dest}))

    for coll_id in plan.delete_empty:
        old = state.collections.get(coll_id)
        old_name = old.name if old else f"#{coll_id}"
        lots["lot-5"].append(Op(
            "lot-5", "delete_collection",
            f"Supprimer la collection vide « {old_name} »",
            {"collection_id": coll_id}))

    return lots
```

- [ ] **Step 4: Lancer le test, vérifier qu'il passe**

Run: `pytest tests/test_reorg_lib.py::test_compute_lots_groups_operations -v`
Expected: PASS.

- [ ] **Step 5: Lancer toute la suite**

Run: `pytest tests/test_reorg_lib.py -v`
Expected: PASS (tous les tests).

- [ ] **Step 6: Commit**

```bash
git add scripts/reorg_lib.py tests/test_reorg_lib.py
git commit -m "reorg: calcul des lots d'opérations à partir du plan"
```

---

## Task 5: Squelette du CLI et connexion Metabase

**Files:**
- Create: `scripts/reorg_phase1.py`

- [ ] **Step 1: Créer `scripts/reorg_phase1.py` avec le CLI et la connexion**

```python
#!/usr/bin/env python3
"""CLI de migration Phase 1 de la collection Metabase « 2. Generic Questions ».

Sous-commandes : snapshot | plan | apply | verify | rollback.
Voir docs/superpowers/specs/2026-05-20-generic-questions-reorg-phase1-design.md
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

from spark_metabase_api import Metabase_API  # noqa: E402

MIGRATION_DIR = REPO_ROOT / "migration"


def _load_env() -> dict:
    """Lit les paires KEY=VALUE de .env (sans dépendance externe)."""
    env = {}
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def connect() -> Metabase_API:
    """Connexion Metabase depuis .env (session_id prioritaire)."""
    env = _load_env()
    domain = env.get("METABASE_DOMAIN") or os.environ.get("METABASE_DOMAIN")
    session_id = env.get("METABASE_SESSION_ID") or os.environ.get("METABASE_SESSION_ID")
    email = env.get("METABASE_EMAIL") or os.environ.get("METABASE_EMAIL")
    password = env.get("METABASE_PASSWORD") or os.environ.get("METABASE_PASSWORD")
    if not domain:
        sys.exit("METABASE_DOMAIN manquant (.env ou environnement).")
    if session_id:
        mb = Metabase_API(domain=domain, session_id=session_id)
        if mb.is_session_valid():
            return mb
        print("session_id expiré — bascule sur email/password.")
    if not (email and password):
        sys.exit("Aucune session valide et METABASE_EMAIL/PASSWORD manquants.")
    return Metabase_API(domain=domain, email=email, password=password)


def cmd_snapshot(args):
    raise NotImplementedError


def cmd_plan(args):
    raise NotImplementedError


def cmd_apply(args):
    raise NotImplementedError


def cmd_verify(args):
    raise NotImplementedError


def cmd_rollback(args):
    raise NotImplementedError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Migration Phase 1 collection 215")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("snapshot", help="Capturer l'état du sous-arbre 215")

    p_plan = sub.add_parser("plan", help="Dry-run : afficher tous les déplacements")
    p_plan.add_argument("--snapshot", required=True)
    p_plan.add_argument("--plan", default=str(MIGRATION_DIR / "phase1-plan.yaml"))

    p_apply = sub.add_parser("apply", help="Exécuter un lot du plan")
    p_apply.add_argument("lot", choices=[f"lot-{i}" for i in range(1, 6)])
    p_apply.add_argument("--snapshot", required=True)
    p_apply.add_argument("--plan", default=str(MIGRATION_DIR / "phase1-plan.yaml"))
    p_apply.add_argument("--yes", action="store_true", help="Sans confirmation")

    p_verify = sub.add_parser("verify", help="Comparer l'état live au snapshot")
    p_verify.add_argument("--snapshot", required=True)

    p_rollback = sub.add_parser("rollback", help="Restaurer les positions du snapshot")
    p_rollback.add_argument("--snapshot", required=True)
    p_rollback.add_argument("--yes", action="store_true")

    args = parser.parse_args(argv)
    {"snapshot": cmd_snapshot, "plan": cmd_plan, "apply": cmd_apply,
     "verify": cmd_verify, "rollback": cmd_rollback}[args.command](args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Vérifier que le CLI se charge et affiche l'aide**

Run: `python scripts/reorg_phase1.py --help`
Expected: l'aide liste les sous-commandes `snapshot, plan, apply, verify, rollback`.

- [ ] **Step 3: Commit**

```bash
git add scripts/reorg_phase1.py
git commit -m "reorg: squelette CLI + connexion Metabase depuis .env"
```

---

## Task 6: Capture d'état et commande `snapshot`

**Files:**
- Modify: `scripts/reorg_lib.py` (ajouter `capture_state`)
- Modify: `scripts/reorg_phase1.py` (implémenter `cmd_snapshot`)
- Test: `tests/test_reorg_lib.py`

`capture_state` parcourt récursivement le sous-arbre d'une collection racine. Elle
prend une fonction `get(endpoint)` en argument (pas l'objet Metabase) pour être
testable avec un faux client. Elle exclut le sous-arbre `EXCLUDE_COLLECTION_ID` du
parcours des cartes mais enregistre la collection elle-même.

- [ ] **Step 1: Écrire le test de `capture_state` avec un faux client**

Ajouter dans `tests/test_reorg_lib.py` :

```python
from reorg_lib import capture_state


def test_capture_state_walks_tree_and_excludes_conversions():
    # Faux backend : réponses canned indexées par endpoint.
    items = {
        "/api/collection/215/items?limit=2000": {"data": [
            {"model": "collection", "id": 214, "name": "01. Global"},
            {"model": "collection", "id": 11673, "name": "18. Nouvelles Conversions"},
            {"model": "card", "id": 29, "name": "CAC"},
        ]},
        "/api/collection/214/items?limit=2000": {"data": [
            {"model": "card", "id": 46255, "name": "Loose card"},
        ]},
        # le sous-arbre de 11673 ne doit jamais être demandé
    }
    cards = {
        29: {"id": 29, "name": "CAC", "collection_id": 215,
             "dashboard_count": 1211, "archived": False},
        46255: {"id": 46255, "name": "Loose card", "collection_id": 214,
                "dashboard_count": 0, "archived": False},
    }

    def fake_get(endpoint):
        if "/items" in endpoint:
            return items[endpoint]
        card_id = int(endpoint.split("/")[-1])
        return cards[card_id]

    state = capture_state(fake_get, root_id=215)
    assert set(state.collections) == {215, 214, 11673}
    assert set(state.cards) == {29, 46255}
    assert state.collections[214].parent_id == 215
```

- [ ] **Step 2: Lancer le test, vérifier qu'il échoue**

Run: `pytest tests/test_reorg_lib.py::test_capture_state_walks_tree_and_excludes_conversions -v`
Expected: FAIL — `ImportError: cannot import name 'capture_state'`.

- [ ] **Step 3: Implémenter `capture_state` dans `scripts/reorg_lib.py`**

```python
def capture_state(get, root_id: int = ROOT_COLLECTION_ID) -> MetabaseState:
    """Parcourt le sous-arbre `root_id` et capture collections + cartes.

    `get` est une fonction `endpoint -> json`. Le sous-arbre
    EXCLUDE_COLLECTION_ID est enregistré comme collection mais son contenu
    n'est pas parcouru.
    """
    collections: dict[int, CollectionNode] = {
        root_id: CollectionNode(id=root_id, name="(root)", parent_id=None)
    }
    cards: dict[int, CardRef] = {}

    def walk(coll_id: int):
        items = get(f"/api/collection/{coll_id}/items?limit=2000").get("data", [])
        for it in items:
            if it["model"] == "collection":
                collections[it["id"]] = CollectionNode(
                    id=it["id"], name=it["name"], parent_id=coll_id)
                if it["id"] != EXCLUDE_COLLECTION_ID:
                    walk(it["id"])
            elif it["model"] in ("card", "dataset"):
                detail = get(f"/api/card/{it['id']}")
                cards[it["id"]] = CardRef(
                    id=detail["id"], name=detail["name"],
                    collection_id=detail.get("collection_id"),
                    dashboard_count=detail.get("dashboard_count", 0),
                    archived=bool(detail.get("archived", False)))

    walk(root_id)
    return MetabaseState(collections=collections, cards=cards)
```

- [ ] **Step 4: Lancer le test, vérifier qu'il passe**

Run: `pytest tests/test_reorg_lib.py::test_capture_state_walks_tree_and_excludes_conversions -v`
Expected: PASS.

- [ ] **Step 5: Implémenter `cmd_snapshot` dans `scripts/reorg_phase1.py`**

Ajouter les imports en tête : `import json`, `from datetime import datetime`,
`from reorg_lib import capture_state, ROOT_COLLECTION_ID`. Remplacer `cmd_snapshot` :

```python
def cmd_snapshot(args):
    mb = connect()
    print(f"Capture du sous-arbre de la collection {ROOT_COLLECTION_ID}...")
    state = capture_state(mb.get, root_id=ROOT_COLLECTION_ID)
    MIGRATION_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = MIGRATION_DIR / f"snapshot-{ts}.json"
    out.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False))
    print(f"  {len(state.collections)} collections, {len(state.cards)} cartes")
    print(f"Snapshot écrit : {out}")
```

- [ ] **Step 6: Exécuter `snapshot` en réel (lecture seule)**

Run: `python scripts/reorg_phase1.py snapshot`
Expected: affiche ~222 collections et ~3181 cartes ; crée `migration/snapshot-<ts>.json`.
Note : si « session_id expiré », rafraîchir `METABASE_SESSION_ID` dans `.env`.

- [ ] **Step 7: Commit**

```bash
git add scripts/reorg_lib.py scripts/reorg_phase1.py tests/test_reorg_lib.py
git commit -m "reorg: capture d'état et commande snapshot"
```

---

## Task 7: Commande `plan` (dry-run)

**Files:**
- Modify: `scripts/reorg_phase1.py` (implémenter `cmd_plan`)

- [ ] **Step 1: Implémenter `cmd_plan` dans `scripts/reorg_phase1.py`**

Ajouter à l'import `reorg_lib` : `load_plan, compute_lots, MetabaseState`.
Remplacer `cmd_plan` :

```python
def cmd_plan(args):
    state = MetabaseState.from_dict(json.loads(Path(args.snapshot).read_text()))
    plan = load_plan(args.plan)
    lots = compute_lots(state, plan)
    total = 0
    for lot_name in (f"lot-{i}" for i in range(1, 6)):
        ops = lots[lot_name]
        print(f"\n=== {lot_name} ({len(ops)} opérations) ===")
        for op in ops:
            print(f"  - {op.summary}")
        total += len(ops)
    print(f"\nTotal : {total} opérations. (DRY-RUN — rien n'a été modifié.)")
```

- [ ] **Step 2: Vérifier le dry-run sur un plan minimal**

Créer un fichier de test temporaire `migration/phase1-plan.yaml` minimal (une
famille, un `delete_empty`), puis :

Run: `python scripts/reorg_phase1.py plan --snapshot migration/snapshot-<ts>.json`
Expected: affiche les 5 lots et se termine par « DRY-RUN — rien n'a été modifié ».

- [ ] **Step 3: Commit**

```bash
git add scripts/reorg_phase1.py
git commit -m "reorg: commande plan (dry-run du diff)"
```

---

## Task 8: Commande `apply` avec vérification post-lot

**Files:**
- Modify: `scripts/reorg_phase1.py` (implémenter `cmd_apply`)

`apply` exécute un lot, puis re-capture l'état et lance `verify_invariant` contre le
snapshot baseline. Toute divergence → arrêt avec code de sortie non nul. `lot-1`
écrit `migration/families.json` (clé -> id créé) ; `lot-2` le relit pour résoudre
`new_parent_key`.

- [ ] **Step 1: Implémenter `cmd_apply` et ses helpers dans `scripts/reorg_phase1.py`**

Ajouter à l'import `reorg_lib` : `verify_invariant, TO_SORT_COLLECTION_ID`.
Remplacer `cmd_apply` et ajouter les helpers :

```python
FAMILIES_FILE_NAME = "families.json"


def _families_path():
    return MIGRATION_DIR / FAMILIES_FILE_NAME


def _check(status, what):
    """`mb.put` renvoie un code HTTP — on échoue fort si non-2xx."""
    if not (200 <= int(status) < 300):
        raise RuntimeError(f"{what} a échoué — HTTP {status}")


def _exec_op(mb, op, family_ids):
    if op.kind == "create_collection":
        coll = mb.create_collection(
            collection_name=op.payload["name"],
            parent_collection_id=ROOT_COLLECTION_ID,
            return_results=True)
        if not coll:
            raise RuntimeError(f"Échec création collection {op.payload['name']!r}")
        desc = op.payload.get("description", "")
        if desc:
            _check(mb.put(f"/api/collection/{coll['id']}",
                          json={"description": desc}), "MAJ description")
        family_ids[op.payload["key"]] = coll["id"]
        print(f"  créée : {op.payload['name']} (id {coll['id']})")
    elif op.kind == "move_collection":
        key = op.payload["new_parent_key"]
        parent = ROOT_COLLECTION_ID if key == "root" else family_ids[key]
        _check(mb.put(f"/api/collection/{op.payload['collection_id']}",
                      json={"parent_id": parent, "name": op.payload["new_name"]}),
               f"déplacement collection {op.payload['collection_id']}")
        print(f"  déplacée : collection {op.payload['collection_id']} "
              f"-> parent {parent}")
    elif op.kind == "move_card":
        _check(mb.put(f"/api/card/{op.payload['card_id']}",
                      json={"collection_id": op.payload["collection_id"]}),
               f"déplacement carte {op.payload['card_id']}")
        print(f"  carte {op.payload['card_id']} -> "
              f"collection {op.payload['collection_id']}")
    elif op.kind == "delete_collection":
        cid = op.payload["collection_id"]
        resp = mb.get(f"/api/collection/{cid}/items?limit=10")
        if resp is False:
            raise RuntimeError(f"impossible de lister la collection {cid}")
        items = resp.get("data", [])
        if items:
            print(f"  IGNORÉE : collection {cid} non vide "
                  f"({len(items)} éléments) — suppression annulée")
            return
        _check(mb.put(f"/api/collection/{cid}", json={"archived": True}),
               f"archivage collection {cid}")
        print(f"  collection {cid} archivée (vide)")
    else:
        raise ValueError(f"opération inconnue : {op.kind}")


def cmd_apply(args):
    baseline = MetabaseState.from_dict(json.loads(Path(args.snapshot).read_text()))
    plan = load_plan(args.plan)
    lots = compute_lots(baseline, plan)
    ops = lots[args.lot]
    if not ops:
        print(f"{args.lot} : aucune opération.")
        return

    print(f"\n=== {args.lot} : {len(ops)} opérations ===")
    for op in ops:
        print(f"  - {op.summary}")
    if not args.yes:
        if input(f"\nAppliquer {args.lot} ? [tape 'oui'] ").strip() != "oui":
            sys.exit("Annulé.")

    mb = connect()
    family_ids = {}
    if _families_path().exists():
        family_ids = json.loads(_families_path().read_text())

    for op in ops:
        _exec_op(mb, op, family_ids)

    if args.lot == "lot-1":
        _families_path().write_text(json.dumps(family_ids, indent=2))
        print(f"Familles enregistrées : {_families_path()}")

    print("\nVérification d'invariant post-lot...")
    current = capture_state(mb.get, root_id=ROOT_COLLECTION_ID)
    divergences = verify_invariant(baseline, current)
    if divergences:
        print("DIVERGENCES DÉTECTÉES — ARRÊT :")
        for d in divergences:
            print(f"  [{d.kind}] carte {d.card_id} : {d.detail}")
        sys.exit(1)
    print(f"OK — {len(current.cards)} cartes intactes, 0 divergence.")
```

- [ ] **Step 2: Vérifier que `apply` refuse sans confirmation**

Run: `echo "non" | python scripts/reorg_phase1.py apply lot-1 --snapshot migration/snapshot-<ts>.json`
Expected: se termine par « Annulé. » sans aucun appel d'écriture.

- [ ] **Step 3: Commit**

```bash
git add scripts/reorg_phase1.py
git commit -m "reorg: commande apply avec vérification d'invariant post-lot"
```

---

## Task 9: Commandes `verify` et `rollback`

**Files:**
- Modify: `scripts/reorg_phase1.py` (implémenter `cmd_verify`, `cmd_rollback`)

- [ ] **Step 1: Implémenter `cmd_verify` et `cmd_rollback`**

Remplacer les deux fonctions :

```python
def cmd_verify(args):
    baseline = MetabaseState.from_dict(json.loads(Path(args.snapshot).read_text()))
    mb = connect()
    current = capture_state(mb.get, root_id=ROOT_COLLECTION_ID)
    divergences = verify_invariant(baseline, current)
    if divergences:
        print(f"{len(divergences)} divergence(s) :")
        for d in divergences:
            print(f"  [{d.kind}] carte {d.card_id} : {d.detail}")
        sys.exit(1)
    print(f"OK — {len(current.cards)} cartes, 0 divergence vs snapshot.")


def cmd_rollback(args):
    baseline = MetabaseState.from_dict(json.loads(Path(args.snapshot).read_text()))
    if not args.yes:
        if input("Restaurer toutes les positions du snapshot ? [tape 'oui'] "
                 ).strip() != "oui":
            sys.exit("Annulé.")
    mb = connect()
    current = capture_state(mb.get, root_id=ROOT_COLLECTION_ID)

    # Restaurer collection_id de chaque carte déplacée.
    for cid, base in baseline.cards.items():
        cur = current.cards.get(cid)
        if cur and cur.collection_id != base.collection_id:
            mb.put(f"/api/card/{cid}", json={"collection_id": base.collection_id})
            print(f"  carte {cid} restaurée -> collection {base.collection_id}")

    # Restaurer parent_id de chaque collection déplacée (présente dans le snapshot).
    for coll_id, base in baseline.collections.items():
        if coll_id == ROOT_COLLECTION_ID:
            continue
        cur = current.collections.get(coll_id)
        if cur and cur.parent_id != base.parent_id:
            mb.put(f"/api/collection/{coll_id}",
                   json={"parent_id": base.parent_id, "name": base.name})
            print(f"  collection {coll_id} restaurée -> parent {base.parent_id}")

    print("Rollback terminé. Les familles créées (absentes du snapshot) "
          "sont à archiver manuellement si besoin.")
```

- [ ] **Step 2: Vérifier `verify` contre le snapshot (état non encore modifié)**

Run: `python scripts/reorg_phase1.py verify --snapshot migration/snapshot-<ts>.json`
Expected: « OK — N cartes, 0 divergence vs snapshot. »

- [ ] **Step 3: Lancer toute la suite de tests**

Run: `pytest tests/test_reorg_lib.py -v`
Expected: PASS (tous les tests).

- [ ] **Step 4: Commit**

```bash
git add scripts/reorg_phase1.py
git commit -m "reorg: commandes verify et rollback"
```

---

## Task 10: Validation end-to-end en lecture seule

**Files:** aucun fichier modifié — tâche de validation.

- [ ] **Step 1: Snapshot frais**

Run: `python scripts/reorg_phase1.py snapshot`
Expected: ~222 collections, ~3181 cartes ; nouveau fichier snapshot.

- [ ] **Step 2: Vérifier que la collection Conversions est bien capturée mais exclue du parcours**

Run: `python -c "import json,glob; s=json.load(open(sorted(glob.glob('migration/snapshot-*.json'))[-1])); ids={c['id'] for c in s['collections']}; print('11673 présent:', 11673 in ids); print('cartes:', len(s['cards']))"`
Expected: `11673 présent: True` ; le nombre de cartes est ~1212 (sous-arbre Conversions non parcouru) — confirme que `EXCLUDE_COLLECTION_ID` fonctionne.

- [ ] **Step 3: Vérifier l'idempotence de `verify`**

Run: `python scripts/reorg_phase1.py verify --snapshot migration/snapshot-<ts>.json`
Expected: « 0 divergence » (l'état n'a pas changé).

- [ ] **Step 4: Ignorer les artefacts runtime de migration + commit**

Les snapshots et `families.json` sont volumineux et régénérables — on ne les
versionne pas. Ajouter à `.gitignore` :

```
# Migration Phase 1 — artefacts runtime (régénérables)
migration/snapshot-*.json
migration/families.json
```

```bash
git add .gitignore
git commit -m "reorg: ignorer les artefacts runtime de migration"
```

---

## Runbook d'exécution (NON auto-exécutable — gates humains)

Ces étapes effectuent la migration live et comportent des validations humaines.
Elles sont menées **interactivement avec l'utilisateur**, pas par un worker autonome.

1. **Snapshot baseline** — `python scripts/reorg_phase1.py snapshot`, commité.
2. **Générer `migration/phase1-plan.yaml`** — depuis le snapshot et le mapping §4 de
   `docs/generic-questions-reorg.md` : les 4 familles, les ~14 `collection_moves`,
   les `delete_empty` (collections vides), et le `card_filing` des 425 cartes en vrac
   de `01. Global` + 9 cartes de `To sort`. Le `card_filing` est produit en analysant
   le nom et la requête de chaque carte. → **GATE : l'utilisateur relit et valide le
   `card_filing` avant tout `apply`.**
3. **Dry-run** — `python scripts/reorg_phase1.py plan --snapshot <snap>` → relecture
   du diff complet par l'utilisateur.
4. **`apply lot-1`** — créer les 4 familles.
5. **`apply lot-2`** — déplacer/renommer les collections (vérif. post-lot auto).
6. **`apply lot-3`** — ranger les cartes en vrac de Global (vérif. post-lot auto).
7. **`apply lot-4`** — dispatcher les 9 cartes « To sort » (vérif. post-lot auto).
8. **`apply lot-5`** — supprimer les collections vides (vérif. post-lot auto).
9. **`verify` final** — `python scripts/reorg_phase1.py verify --snapshot <snap>` :
   0 carte perdue, 0 archivée, tous les `dashboard_count` identiques.
10. **Figer** — `spark-metabase export "2. Generic Questions"
    specs/generic-questions.yaml`, commité. Évolutions futures via `plan`/`apply` IaC.

En cas de divergence à n'importe quel lot : `apply` s'arrête seul ;
`python scripts/reorg_phase1.py rollback --snapshot <snap>` restaure l'état.

---

## Notes de mise en œuvre

- **`create_collection`** : signature
  `create_collection(collection_name, parent_collection_id=None, ...,
  return_results=False)` — pas de paramètre `description`. La description est
  posée par un `PUT /api/collection/{id}` séparé. La librairie gère déjà le repli
  sur la version Metabase (champ `color`).
- **`mb.put` / `mb.delete`** renvoient un **code HTTP** (pas du JSON) ; `mb.get` /
  `mb.post` renvoient le JSON ou `False`. `_exec_op` contrôle chaque code via
  `_check` pour qu'un PUT échoué ne passe pas silencieusement.
- **Suppression de collection** : Metabase archive (il n'existe pas de hard-delete
  d'API simple) — `PUT {archived: true}` sur une collection vide. C'est réversible.
- **`dashboard_count` modifié** : peut provenir d'une édition concurrente par un
  tiers pendant la migration, pas forcément du script. Si `verify` le signale,
  investiguer la carte concernée avant de conclure à une régression.
- **Renommage des cartes interdit** : aucune opération de ce plan ne modifie le
  champ `name` d'une carte — uniquement celui des collections.
