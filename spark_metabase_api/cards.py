"""Lecture et écriture de cartes, avec les pièges de forme déjà bouchés.

Le piège. Depuis le passage à MBQL5, `GET /api/card/{id}` ne rend plus la
forme historique :

    GET /api/card/32496                   -> dataset_query = {database, lib/type, stages}
                                             et dataset_query["type"] vaut None
    GET /api/card/32496?legacy-mbql=true  -> dataset_query = {database, native, type}
                                             et dataset_query["type"] vaut 'native'

Tout le code du dépôt (et l'ancien validate.check_structure) lit `type` et
`native`. Sans le paramètre, il reçoit None et conclut « unknown query type »
sur TOUTES les cartes de la prod.

`get_card()` ajoute donc toujours le paramètre. Un agent ne peut plus tomber
dans le piège en oubliant un détail d'URL.
"""

from typing import Any, Dict, Optional

from . import http
from .http import MetabaseError


def get_card(client, card_id: int, mbql5: bool = False) -> Dict[str, Any]:
    """Renvoie une carte sous la forme legacy (`dataset_query.type` renseigné).

    mbql5=True pour la forme moderne (stages), à n'utiliser que si on sait
    précisément pourquoi on la veut."""
    suffix = "" if mbql5 else "?legacy-mbql=true"
    return http.get(client, "/api/card/{}{}".format(card_id, suffix))


def card_sql(card: Dict[str, Any]) -> Optional[str]:
    """Extrait le SQL natif d'une carte, quelle que soit la forme reçue.

    Accepte la forme legacy comme la forme MBQL5, parce qu'une carte relue
    après écriture peut arriver dans l'une ou l'autre selon l'appelant."""
    dq = card.get("dataset_query") or {}
    native = dq.get("native")
    if isinstance(native, dict) and native.get("query"):
        return native["query"]
    for stage in dq.get("stages") or []:
        if isinstance(stage, dict) and stage.get("native"):
            return stage["native"]
    return None


def put_card(client, card_id: int, payload: Dict[str, Any],
             verify: bool = True) -> Dict[str, Any]:
    """Écrit une carte, vérifie le status, puis RELIT pour confirmer.

    Lève MetabaseError si l'écriture échoue, et ValueError si la relecture
    montre que la modification n'a pas atterri. Une écriture silencieusement
    perdue devient impossible.
    """
    http.put(client, "/api/card/{}".format(card_id), json=payload)
    if not verify:
        return get_card(client, card_id)

    after = get_card(client, card_id)
    if "dataset_query" in payload:
        wanted = _sql_of_payload(payload)
        if wanted is not None and card_sql(after) != wanted:
            raise ValueError(
                "carte {} : le SQL relu ne correspond pas à celui écrit. "
                "L'écriture a été acceptée mais n'a pas atterri.".format(card_id))
    for champ in ("name", "description", "display", "collection_id", "archived"):
        if champ in payload and after.get(champ) != payload[champ]:
            raise ValueError(
                "carte {} : champ '{}' relu à {!r}, attendu {!r}".format(
                    card_id, champ, after.get(champ), payload[champ]))
    return after


def _sql_of_payload(payload: Dict[str, Any]) -> Optional[str]:
    """Même lecture que card_sql, donc les deux formes.

    En ne lisant que la forme legacy, cette fonction rendait None pour un
    payload MBQL5, ce qui SAUTAIT silencieusement la vérification de put_card
    alors que sa docstring promet l'inverse."""
    return card_sql(payload)


def card_values(client, card_id: int):
    """Valeurs scalaires d'une carte, prêtes pour diff.check_values.

    C'est le format que la migration conv compare : un multiset numérique."""
    data = client.get_card_data(card_id=card_id, data_format="json")
    if not isinstance(data, list):
        return []
    out = []
    for row in data:
        if isinstance(row, dict):
            out.extend(v for v in row.values()
                       if isinstance(v, (int, float)) and not isinstance(v, bool))
    return out


__all__ = ["get_card", "put_card", "card_sql", "card_values", "MetabaseError"]
