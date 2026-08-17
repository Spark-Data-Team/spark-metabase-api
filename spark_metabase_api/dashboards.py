"""Écriture de dashboards, avec le piège des onglets déjà bouché.

Le piège. Un `PUT /api/dashboard/{id}` sur un dashboard à onglets qui n'inclut
pas `tabs` renvoie un 500 (contrainte de clé étrangère sur les dashcards, qui
référencent un onglet que la requête vient d'effacer). Même chose, plus
insidieux, pour `parameters` : les omettre efface les filtres du dashboard
sans lever la moindre erreur.

Trois scripts du dépôt portaient ce bug à la main. `put_dashboard()` refait
toujours GET -> fusion -> réinjection de `tabs` et `parameters` -> écriture ->
relecture. Le 500 devient impossible à déclencher, et un filtre ne peut plus
disparaître par omission.
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
        if champ in ("tabs", "parameters", "dashcards"):
            continue
        if apres.get(champ) != attendu:
            raise ValueError(
                "dashboard {} : champ '{}' relu à {!r}, attendu {!r}".format(
                    dashboard_id, champ, apres.get(champ), attendu))
    return apres


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
