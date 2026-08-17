"""Tests du noyau : http strict, façade de compatibilité, cards, dashboards.

Hors-ligne. Le client est simulé, aucune requête ne part.
"""

import json

import pytest

from spark_metabase_api import cards, dashboards, http
from spark_metabase_api.http import MetabaseError


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})
        self.content = self.text.encode()

    def json(self):
        return self._payload


class FakeHTTP:
    """Remplace requests.Session. Enregistre les appels, rend des réponses scriptées."""

    def __init__(self, routes):
        self.routes = routes  # {(METHOD, endpoint): FakeResponse ou callable}
        self.calls = []

    def request(self, method, url, **kwargs):
        endpoint = url.split("fake.metabase", 1)[-1]
        self.calls.append((method, endpoint, kwargs.get("json")))
        r = self.routes.get((method, endpoint))
        if r is None:
            return FakeResponse(404, {"message": "not found"})
        return r(len([c for c in self.calls if c[1] == endpoint])) if callable(r) else r


class FakeClient:
    def __init__(self, routes):
        self.domain = "https://fake.metabase"
        self.header = {}
        self.auth = None
        self._http = FakeHTTP(routes)

    def validate_session(self):
        return True

    # la façade historique, montée comme sur la vraie classe
    from spark_metabase_api._rest_methods import get, post, put, delete


# --- http strict -------------------------------------------------------------

def test_http_leve_sur_non_2xx():
    c = FakeClient({("GET", "/api/card/1"): FakeResponse(500, text="boom")})
    with pytest.raises(MetabaseError) as e:
        http.get(c, "/api/card/1")
    assert e.value.status == 500
    assert e.value.method == "GET"
    assert "boom" in str(e.value)


def test_http_rend_none_sur_corps_vide():
    """Un 204 est une réussite, pas une erreur de parsing."""
    c = FakeClient({("DELETE", "/api/card/1"): FakeResponse(204, text="")})
    assert http.delete(c, "/api/card/1") is None


# --- façade de compatibilité -------------------------------------------------

def test_facade_get_rend_false_comme_avant():
    c = FakeClient({("GET", "/api/card/1"): FakeResponse(404, text="nope")})
    assert c.get("/api/card/1") is False


def test_facade_put_rend_le_status_code_meme_en_erreur():
    """Contrat historique préservé, y compris son piège : 500 est truthy.

    C'est précisément pour ça que le code nouveau doit utiliser http.put."""
    c = FakeClient({("PUT", "/api/card/1"): FakeResponse(500, text="boom")})
    assert c.put("/api/card/1", json={}) == 500
    assert bool(c.put("/api/card/1", json={})) is True  # le piège, documenté


def test_facade_raw_rend_un_objet_reponse_meme_en_erreur():
    """Les 66 appels .put(..., "raw") lisent .status_code, .text et .ok."""
    c = FakeClient({("PUT", "/api/card/1"): FakeResponse(422, text="invalide")})
    res = c.put("/api/card/1", "raw", json={})
    assert res.status_code == 422
    assert res.ok is False
    assert res.text == "invalide"


# --- cards -------------------------------------------------------------------

def test_get_card_demande_toujours_la_forme_legacy():
    """Le piège MBQL5 : sans ?legacy-mbql=true, dataset_query["type"] vaut None."""
    legacy = {"dataset_query": {"type": "native", "native": {"query": "SELECT 1"}}}
    c = FakeClient({("GET", "/api/card/7?legacy-mbql=true"): FakeResponse(200, legacy)})
    carte = cards.get_card(c, 7)
    assert carte["dataset_query"]["type"] == "native"
    assert c._http.calls[0][1] == "/api/card/7?legacy-mbql=true"


def test_card_sql_lit_les_deux_formes():
    assert cards.card_sql(
        {"dataset_query": {"native": {"query": "SELECT 1"}}}) == "SELECT 1"
    assert cards.card_sql(
        {"dataset_query": {"stages": [{"native": "SELECT 2"}]}}) == "SELECT 2"
    assert cards.card_sql({"dataset_query": {}}) is None


def test_put_card_leve_si_la_relecture_ne_correspond_pas():
    """Une écriture acceptée mais non atterrie doit exploser, pas passer."""
    ecrit = {"dataset_query": {"type": "native", "native": {"query": "SELECT NEW"}}}
    relu = {"dataset_query": {"type": "native", "native": {"query": "SELECT OLD"}}}
    c = FakeClient({
        ("PUT", "/api/card/7"): FakeResponse(200, {}),
        ("GET", "/api/card/7?legacy-mbql=true"): FakeResponse(200, relu),
    })
    with pytest.raises(ValueError, match="n'a pas atterri"):
        cards.put_card(c, 7, ecrit)


def test_put_card_leve_si_un_champ_simple_ne_correspond_pas():
    c = FakeClient({
        ("PUT", "/api/card/7"): FakeResponse(200, {}),
        ("GET", "/api/card/7?legacy-mbql=true"): FakeResponse(200, {"name": "ancien"}),
    })
    with pytest.raises(ValueError, match="champ 'name'"):
        cards.put_card(c, 7, {"name": "nouveau"})


def test_put_card_passe_quand_la_relecture_confirme():
    c = FakeClient({
        ("PUT", "/api/card/7"): FakeResponse(200, {}),
        ("GET", "/api/card/7?legacy-mbql=true"): FakeResponse(200, {"name": "nouveau"}),
    })
    assert cards.put_card(c, 7, {"name": "nouveau"})["name"] == "nouveau"


# --- dashboards --------------------------------------------------------------

def test_put_dashboard_reinjecte_tabs_et_parameters():
    """Le PUT sans tabs sur un dashboard à onglets renvoie un 500 en vrai."""
    etat = {"name": "ancien", "tabs": [{"id": 1}, {"id": 2}],
            "parameters": [{"id": "p1"}], "dashcards": [{"id": 10}]}
    apres = dict(etat, name="nouveau")
    c = FakeClient({
        ("GET", "/api/dashboard/9"): FakeResponse(200, etat),
        ("PUT", "/api/dashboard/9"): FakeResponse(200, {}),
    })
    c._http.routes[("GET", "/api/dashboard/9")] = lambda n: FakeResponse(
        200, etat if n == 1 else apres)

    dashboards.put_dashboard(c, 9, {"name": "nouveau"})

    envoye = [c for c in c._http.calls if c[0] == "PUT"][0][2]
    assert envoye["tabs"] == etat["tabs"], "tabs doit être réinjecté"
    assert envoye["parameters"] == etat["parameters"], "parameters doit être réinjecté"
    assert envoye["name"] == "nouveau"


def test_put_dashboard_leve_si_un_onglet_disparait():
    """Un onglet perdu par omission doit être détecté, pas subi."""
    avant = {"name": "d", "tabs": [{"id": 1}, {"id": 2}], "parameters": [], "dashcards": []}
    apres = {"name": "d2", "tabs": [{"id": 1}], "parameters": [], "dashcards": []}
    c = FakeClient({("PUT", "/api/dashboard/9"): FakeResponse(200, {})})
    c._http.routes[("GET", "/api/dashboard/9")] = lambda n: FakeResponse(
        200, avant if n == 1 else apres)

    with pytest.raises(ValueError, match="tabs"):
        dashboards.put_dashboard(c, 9, {"name": "d2"})


def test_put_dashboard_accepte_une_modification_voulue_des_onglets():
    """Si l'appelant touche explicitement aux tabs, ce n'est pas une perte."""
    avant = {"name": "d", "tabs": [{"id": 1}, {"id": 2}], "parameters": [], "dashcards": []}
    apres = {"name": "d", "tabs": [{"id": 1}], "parameters": [], "dashcards": []}
    c = FakeClient({("PUT", "/api/dashboard/9"): FakeResponse(200, {})})
    c._http.routes[("GET", "/api/dashboard/9")] = lambda n: FakeResponse(
        200, avant if n == 1 else apres)

    res = dashboards.put_dashboard(c, 9, {"tabs": [{"id": 1}]})
    assert len(res["tabs"]) == 1


# --- Passe adversariale (2026-08-17) : trous laissés ouverts ---

def test_put_dashboard_detecte_une_tuile_rejetee_en_silence():
    """Cas d'usage principal du module : recâbler des dashcards. Metabase peut
    accepter le PUT et n'en retenir qu'une partie."""
    avant = {"name": "d", "tabs": [], "parameters": [], "dashcards": [{"id": 1}, {"id": 2}]}
    apres = {"name": "d", "tabs": [], "parameters": [], "dashcards": [{"id": 1}]}
    c = FakeClient({("PUT", "/api/dashboard/9"): FakeResponse(200, {})})
    c._http.routes[("GET", "/api/dashboard/9")] = lambda n: FakeResponse(
        200, avant if n == 1 else apres)

    with pytest.raises(ValueError, match="rejeté 1 en silence"):
        dashboards.put_dashboard(c, 9, {"dashcards": [{"id": 1}, {"id": 3}]})


def test_put_card_verifie_aussi_une_carte_mbql_structuree():
    """card_sql rend None sur une requête MBQL sans SQL, donc la vérification
    était entièrement sautée pour les cartes majoritaires de la migration."""
    ecrit = {"dataset_query": {"type": "query", "database": 2,
                               "query": {"source-table": 123, "aggregation": [["count"]]}}}
    relu = {"dataset_query": {"type": "query", "database": 2,
                              "query": {"source-table": 999, "aggregation": [["count"]]}}}
    c = FakeClient({
        ("PUT", "/api/card/7"): FakeResponse(200, {}),
        ("GET", "/api/card/7?legacy-mbql=true"): FakeResponse(200, relu),
    })
    with pytest.raises(ValueError, match="source-table"):
        cards.put_card(c, 7, ecrit)


def test_put_card_mbql_tolere_l_enrichissement_de_metabase():
    """Metabase normalise et ajoute des clés : on compare ce que l'appelant a
    voulu poser, pas le dict entier."""
    ecrit = {"dataset_query": {"type": "query", "query": {"source-table": 123}}}
    relu = {"dataset_query": {"type": "query",
                              "query": {"source-table": 123, "lib/uuid": "abc"}}}
    c = FakeClient({
        ("PUT", "/api/card/7"): FakeResponse(200, {}),
        ("GET", "/api/card/7?legacy-mbql=true"): FakeResponse(200, relu),
    })
    assert cards.put_card(c, 7, ecrit)
