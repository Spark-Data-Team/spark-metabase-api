"""Écriture de dashboards : réinjection défensive et vérification de relecture.

Historique. Un `PUT /api/dashboard/{id}` omettant `tabs` renvoyait un 500
(clé étrangère des dashcards vers l'onglet effacé), et omettre `parameters`
effaçait les filtres en silence. Trois scripts du dépôt contournaient ça à la
main.

Mesuré le 2026-08-17 sur Metabase v1.63.13 : **ce n'est plus le cas**. Avec
2 onglets et une tuile posée sur un onglet, un `PUT {"name": ...}` nu ne lève
pas et ne perd rien. Metabase préserve les champs omis.

Ce module garde donc son intérêt, mais pas celui qu'on croyait :
  - la réinjection de `tabs`/`parameters`/`dashcards` est désormais une ceinture
    de sécurité peu coûteuse, plus un correctif indispensable ;
  - la vraie valeur est la RELECTURE : vérifier que la modification a atterri,
    qu'aucun onglet, filtre ou tuile n'a disparu, et que le compte d'éléments
    envoyés correspond au compte relu (Metabase rejette en silence une dashcard
    dont le card_id est mort).
"""

from typing import Any, Dict

from . import http
from .http import MetabaseError  # noqa: F401

# Champs qu'un PUT partiel efface silencieusement s'ils sont omis.
_CHAMPS_A_PRESERVER = ("tabs", "parameters", "dashcards")


def get_dashboard(client, dashboard_id: int) -> Dict[str, Any]:
    return http.get(client, "/api/dashboard/{}".format(dashboard_id))


def put_dashboard(client, dashboard_id: int, changes: Dict[str, Any],
                  verify: bool = True) -> Dict[str, Any]:
    """Applique `changes` à un dashboard en préservant sa structure.

    `changes` ne contient QUE ce qu'on veut modifier. Sont relus depuis
    l'instance et réinjectés : `tabs`, `parameters`, `dashcards`, c'est-à-dire
    les trois champs dont l'omission casse ou vide le dashboard.

    Les AUTRES champs (`description`, `collection_id`, `cache_ttl`,
    `auto_apply_filters`, ...) ne sont pas renvoyés : Metabase les conserve sur
    un PUT partiel. Si tu en modifies un, passe-le explicitement dans `changes`.
    """
    avant = get_dashboard(client, dashboard_id)

    payload = dict(changes)
    for champ in _CHAMPS_A_PRESERVER:
        if champ not in payload and avant.get(champ) is not None:
            payload[champ] = avant[champ]

    http.put(client, "/api/dashboard/{}".format(dashboard_id), json=payload)

    if not verify:
        return get_dashboard(client, dashboard_id)

    apres = get_dashboard(client, dashboard_id)
    _verifier_rien_de_perdu(dashboard_id, avant, apres, changes)
    for champ, attendu in changes.items():
        if champ in _CHAMPS_A_PRESERVER:
            # Cas d'usage principal du module : recâbler des tuiles ou des
            # filtres. Metabase peut accepter le PUT et n'en retenir qu'une
            # partie (une dashcard dont le card_id est mort est ignorée en
            # silence). On ne peut pas comparer les objets, qu'il enrichit,
            # mais le compte doit correspondre.
            _verifier_compte(dashboard_id, champ, attendu, apres.get(champ))
            continue
        if apres.get(champ) != attendu:
            raise ValueError(
                "dashboard {} : champ '{}' relu à {!r}, attendu {!r}".format(
                    dashboard_id, champ, apres.get(champ), attendu))
    return apres


def _verifier_compte(dashboard_id, champ, attendu, obtenu) -> None:
    if not isinstance(attendu, list):
        return
    n_attendu, n_obtenu = len(attendu), len(obtenu or [])
    if n_obtenu != n_attendu:
        raise ValueError(
            "dashboard {} : '{}' envoyé avec {} éléments, relu avec {}. "
            "Metabase en a rejeté {} en silence.".format(
                dashboard_id, champ, n_attendu, n_obtenu, abs(n_attendu - n_obtenu)))


def _verifier_rien_de_perdu(dashboard_id, avant, apres, changes) -> None:
    """Un onglet, un filtre ou une tuile ne doit jamais disparaître par accident."""
    for champ in _CHAMPS_A_PRESERVER:
        if champ in changes:
            continue  # modification voulue, pas une perte
        n_avant = len(avant.get(champ) or [])
        n_apres = len(apres.get(champ) or [])
        if n_apres < n_avant:
            raise ValueError(
                "dashboard {} : '{}' est passé de {} à {} éléments alors que "
                "l'appel n'y touchait pas. Écriture à annuler.".format(
                    dashboard_id, champ, n_avant, n_apres))


__all__ = ["get_dashboard", "put_dashboard"]
