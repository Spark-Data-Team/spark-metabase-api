"""Tests du graphe de dépendances natif. Hors-ligne."""

import pytest

from spark_metabase_api import deps
from tests.test_core import FakeClient, FakeResponse

# Un nœud natif embarque la config complète de la base : mesuré à 157 173
# caractères pour la seule carte 32496. On simule ce poids ici.
_NOEUD_VERBEUX = {
    "id": 25268, "type": "table",
    "data": {"name": "KP__KEYWORD_MONTHLY_METRICS", "schema": "GOOGLE_KEYWORD_PLANNER",
             "db": {"features": ["window-functions/cumulative"] * 200,
                    "details": {"host": "x", "warehouse": "REPORTING_WH"}}},
}
_GRAPHE = {
    "nodes": [_NOEUD_VERBEUX, {"id": 32496, "type": "card", "data": {"name": "SERP positions"}}],
    "edges": [{"from_entity_type": "card", "from_entity_id": 32496,
               "to_entity_type": "table", "to_entity_id": 25268}],
}


def _client(routes):
    return FakeClient(routes)


def test_graph_compacte_la_reponse_native():
    c = _client({("GET", "/api/ee/dependencies/graph?id=32496&type=card"):
                 FakeResponse(200, _GRAPHE)})
    g = deps.graph(c, 32496)
    assert g["nodes"][0] == {"id": 25268, "type": "table",
                            "name": "KP__KEYWORD_MONTHLY_METRICS",
                            "schema": "GOOGLE_KEYWORD_PLANNER"}
    assert g["edges"][0] == {"from": ("card", 32496), "to": ("table", 25268)}
    assert "features" not in str(g), "la config de la base ne doit pas ressortir"
    assert len(str(g)) < len(str(_GRAPHE)) / 10


def test_tables_of_ne_rend_que_les_tables():
    c = _client({("GET", "/api/ee/dependencies/graph?id=32496&type=card"):
                 FakeResponse(200, _GRAPHE)})
    tables = deps.tables_of(c, 32496)
    assert [t["name"] for t in tables] == ["KP__KEYWORD_MONTHLY_METRICS"]


def test_type_inconnu_est_refuse_avant_l_appel():
    c = _client({})
    with pytest.raises(ValueError, match="type inconnu"):
        deps.graph(c, 1, "carte")
    assert c._http.calls == [], "aucune requête ne doit partir"


def test_unreferenced_leve_tant_que_le_backfill_est_incomplet():
    """L'endpoint remonte du vivant comme mort dans cet état : sonde live, il a
    rendu le dashboard 673 vu 6 547 fois pour une requête type=card."""
    c = _client({("GET", "/api/ee/dependencies/backfill-status"):
                 FakeResponse(200, {"complete": False})})
    with pytest.raises(deps.BackfillIncomplet, match="complete=false"):
        deps.unreferenced(c)
    assert not any("unreferenced" in call[1] for call in c._http.calls), \
        "on ne doit même pas interroger l'endpoint"


def test_unreferenced_repond_quand_le_backfill_est_termine():
    c = _client({
        ("GET", "/api/ee/dependencies/backfill-status"): FakeResponse(200, {"complete": True}),
        ("GET", "/api/ee/dependencies/graph/unreferenced?type=card&limit=50"):
            FakeResponse(200, {"data": [{"id": 5, "type": "card", "data": {"name": "orpheline"}}]}),
    })
    res = deps.unreferenced(c)
    assert res == [{"id": 5, "type": "card", "name": "orpheline"}]


def test_broken_rend_une_liste_vide_quand_rien_n_est_casse():
    c = _client({("GET", "/api/ee/dependencies/graph/broken?id=32496&type=card"):
                 FakeResponse(200, [])})
    assert deps.broken(c, 32496) == []
