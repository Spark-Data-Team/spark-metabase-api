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
