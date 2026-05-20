"""Logique pure de la migration Phase 1 — aucun effet de bord, aucun réseau."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

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
