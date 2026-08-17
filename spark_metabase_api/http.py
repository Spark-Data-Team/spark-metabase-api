"""Couche HTTP stricte : toute réponse non-2xx lève.

Pourquoi ce module existe. L'ancienne couche (`_rest_methods`) mentait sur
l'issue d'une requête :

    put()    renvoyait res.status_code  ->  500 est truthy, donc
                                            `if mb.put(...)` réussissait sur
                                            une erreur serveur
    get()    renvoyait False sur erreur ->  indiscernable d'un résultat vide
                                            légitime

Conséquence mesurée : 66 des 110 appels `.put(` du dépôt passaient `"raw"`
pour contourner la bibliothèque. Ici, une écriture qui échoue lève, point.

`_rest_methods` reste en façade et rattrape ces exceptions pour rendre les
anciennes valeurs, le temps que les scripts migrent.
"""

from typing import Any, Optional

DEFAULT_TIMEOUT = 30
_BODY_EXCERPT = 500


class MetabaseError(RuntimeError):
    """Une requête Metabase a échoué. Porte de quoi diagnostiquer sans relancer."""

    def __init__(self, method: str, endpoint: str, status: int, body: str):
        self.method = method.upper()
        self.endpoint = endpoint
        self.status = status
        self.body = body
        super().__init__("{} {} -> HTTP {}\n{}".format(
            self.method, endpoint, status, (body or "")[:_BODY_EXCERPT]))


def request(client, method: str, endpoint: str, **kwargs):
    """Exécute la requête et lève MetabaseError sur tout non-2xx.

    Renvoie l'objet Response de requests."""
    client.validate_session()
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    if getattr(client, "_http", None) is None:
        # Filet pour les sous-classes construites avant l'existence de _http.
        import requests
        client._http = requests.Session()
    res = client._http.request(
        method.upper(), client.domain + endpoint,
        headers=client.header, auth=client.auth, **kwargs)
    if not res.ok:
        raise MetabaseError(method, endpoint, res.status_code, res.text)
    return res


def _json(res) -> Optional[Any]:
    """Corps JSON, ou None si le corps est vide (un 204 est une réussite)."""
    if not res.content:
        return None
    try:
        return res.json()
    except ValueError:
        return None


def get(client, endpoint: str, **kwargs) -> Optional[Any]:
    return _json(request(client, "GET", endpoint, **kwargs))


def post(client, endpoint: str, **kwargs) -> Optional[Any]:
    return _json(request(client, "POST", endpoint, **kwargs))


def put(client, endpoint: str, **kwargs) -> Optional[Any]:
    return _json(request(client, "PUT", endpoint, **kwargs))


def delete(client, endpoint: str, **kwargs) -> Optional[Any]:
    return _json(request(client, "DELETE", endpoint, **kwargs))
