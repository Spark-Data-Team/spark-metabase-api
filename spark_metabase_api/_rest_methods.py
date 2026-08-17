"""Façade de compatibilité au-dessus de `http.py`.

Ces quatre méthodes gardent EXACTEMENT leur valeur de retour historique
(`False` / `status_code` / l'objet Response avec `"raw"`), pour que les 104
scripts existants ne changent pas de comportement du jour au lendemain.

Le code nouveau ne doit pas les utiliser : appeler `spark_metabase_api.http`
directement, ou les fonctions de `cards.py` / `dashboards.py` qui bouchent en
plus les pièges de forme de l'API.

Il n'y a plus qu'une seule implémentation HTTP, dans `http.py`.
"""

from . import http
from .http import DEFAULT_TIMEOUT, MetabaseError  # noqa: F401  (ré-export historique)


def get(self, endpoint, *args, **kwargs):
    try:
        res = http.request(self, "GET", endpoint, **kwargs)
    except MetabaseError as e:
        if "raw" in args:
            return _fake_response(e)
        return False
    if "raw" in args:
        return res
    return http._json(res)


def post(self, endpoint, *args, **kwargs):
    try:
        res = http.request(self, "POST", endpoint, **kwargs)
    except MetabaseError as e:
        if "raw" in args:
            return _fake_response(e)
        return False
    if "raw" in args:
        return res
    return http._json(res)


def put(self, endpoint, *args, **kwargs):
    """Met à jour un objet (carte, dashboard, ...).

    ATTENTION : la valeur de retour est un status_code, donc TOUJOURS truthy,
    500 compris. Ne jamais écrire `if mb.put(...)`. Le code nouveau utilise
    `spark_metabase_api.http.put`, qui lève.
    """
    try:
        res = http.request(self, "PUT", endpoint, **kwargs)
    except MetabaseError as e:
        if "raw" in args:
            return _fake_response(e)
        return e.status
    if "raw" in args:
        return res
    return res.status_code


def delete(self, endpoint, *args, **kwargs):
    try:
        res = http.request(self, "DELETE", endpoint, **kwargs)
    except MetabaseError as e:
        if "raw" in args:
            return _fake_response(e)
        return e.status
    if "raw" in args:
        return res
    return res.status_code


class _FakeResponse:
    """Reconstitue le minimum d'une Response pour les appelants en mode "raw".

    Les 66 appels `.put(..., "raw")` du dépôt lisent `.status_code`, `.text`,
    `.ok` et parfois `.json()`. On préserve ce contrat.
    """

    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text
        self.ok = 200 <= status_code < 300
        self.content = (text or "").encode()

    def json(self):
        import json
        return json.loads(self.text)


def _fake_response(err):
    return _FakeResponse(err.status, err.body)
