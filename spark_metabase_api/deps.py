"""Graphe de dépendances natif de Metabase, en version lisible.

Pourquoi le natif plutôt que notre regex. Le dépôt cherchait les dépendances
d'une carte avec `card__(\\d+)` recopié dans 16 fichiers. Sur la carte 32496
(SQL natif Snowflake, aucun `card__`), cette regex ne voit rien, alors que le
natif résout les 8 tables réellement lues. Le natif n'est pas équivalent, il
est strictement supérieur.

Pourquoi cette enveloppe plutôt que l'endpoint brut. La réponse native embarque
la configuration complète de la base dans chaque nœud : mesuré à 157 173
caractères pour UNE carte. Un agent qui appelle l'endpoint directement perd son
contexte. Ici on rend {id, type, name, schema} et des arêtes en tuples.

Pourquoi `unreferenced()` refuse de répondre. `backfill-status` vaut
`{"complete": false}` sur l'instance. Dans cet état l'endpoint remonte du
vivant comme mort : une sonde `type=card&limit=2` a rendu le dashboard 673,
vu 6 547 fois. S'en servir pour archiver détruirait du contenu utilisé.
"""

from typing import Any, Dict, List, Optional

from . import http

_TYPES = ("card", "dashboard", "table", "snippet", "transform")


class BackfillIncomplet(RuntimeError):
    """Le graphe natif n'a pas fini de se construire : ses réponses sont fausses."""


def backfill_complet(client) -> bool:
    """Le graphe de dépendances est-il utilisable pour décider d'un archivage ?"""
    res = http.get(client, "/api/ee/dependencies/backfill-status") or {}
    return bool(res.get("complete"))


def _compacter_noeud(n: Dict[str, Any]) -> Dict[str, Any]:
    d = n.get("data") or {}
    out = {"id": n.get("id"), "type": n.get("type"),
           "name": d.get("name") or d.get("display_name")}
    if d.get("schema"):
        out["schema"] = d["schema"]
    return out


def _compacter_arete(e: Dict[str, Any]) -> Dict[str, Any]:
    return {"from": (e.get("from_entity_type"), e.get("from_entity_id")),
            "to": (e.get("to_entity_type"), e.get("to_entity_id"))}


def graph(client, entity_id: int, entity_type: str = "card") -> Dict[str, Any]:
    """Graphe de dépendances d'une entité, compacté.

    Renvoie {"nodes": [{id, type, name, schema?}], "edges": [{from, to}]}."""
    if entity_type not in _TYPES:
        raise ValueError("type inconnu {!r}, attendu l'un de {}".format(entity_type, _TYPES))
    brut = http.get(client, "/api/ee/dependencies/graph?id={}&type={}".format(
        entity_id, entity_type)) or {}
    return {"nodes": [_compacter_noeud(n) for n in brut.get("nodes") or []],
            "edges": [_compacter_arete(e) for e in brut.get("edges") or []]}


def tables_of(client, card_id: int) -> List[Dict[str, Any]]:
    """Tables réellement lues par une carte, SQL natif compris.

    C'est le remplacement direct de la regex `card__(\\d+)` et du grep textuel
    `schema.table` de `find_cards_via_db_object`."""
    return [n for n in graph(client, card_id, "card")["nodes"] if n["type"] == "table"]


def broken(client, entity_id: int, entity_type: str = "card") -> List[Dict[str, Any]]:
    """Dépendances cassées de cette entité. Liste vide = rien de cassé."""
    brut = http.get(client, "/api/ee/dependencies/graph/broken?id={}&type={}".format(
        entity_id, entity_type))
    return [_compacter_noeud(n) for n in (brut or [])]


def breaking(client, entity_id: int, entity_type: str = "card") -> List[Dict[str, Any]]:
    """Ce que casserait une modification de cette entité."""
    brut = http.get(client, "/api/ee/dependencies/graph/breaking?id={}&type={}".format(
        entity_id, entity_type)) or {}
    return [_compacter_noeud(n) for n in brut.get("data") or []]


def unreferenced(client, entity_type: str = "card", limit: int = 50,
                 force: bool = False) -> List[Dict[str, Any]]:
    """Entités que le natif dit non référencées.

    LÈVE tant que le backfill n'est pas terminé : dans cet état les réponses
    sont fausses et archiver sur cette base détruirait du contenu vivant.
    `force=True` n'est là que pour inspecter, jamais pour décider d'un archivage.
    """
    if not force and not backfill_complet(client):
        raise BackfillIncomplet(
            "backfill-status: complete=false. Le graphe natif remonte encore du "
            "vivant comme non référencé (sonde: dashboard 673, vu 6 547 fois). "
            "Ne pas s'en servir pour archiver. Repasser quand complete=true.")
    brut = http.get(client, "/api/ee/dependencies/graph/unreferenced?type={}&limit={}".format(
        entity_type, limit)) or {}
    return [_compacter_noeud(n) for n in brut.get("data") or []]


__all__ = ["graph", "tables_of", "broken", "breaking", "unreferenced",
           "backfill_complet", "BackfillIncomplet"]
