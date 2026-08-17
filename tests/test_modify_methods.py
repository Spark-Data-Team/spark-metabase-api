"""Deux bugs de logique du wrapper qui écrivaient en prod sans le dire."""

import pytest

from spark_metabase_api import modify_methods
from tests.test_core import FakeClient, FakeResponse


class Client(FakeClient):
    """FakeClient + les deux méthodes modifiées et leurs dépendances."""

    restrict_collection_access = modify_methods.restrict_collection_access
    restrict_filter_with_card_values = modify_methods.restrict_filter_with_card_values

    def verbose_print(self, verbose, msg):
        pass

    def get_item_id(self, kind, name):
        return 42


def test_restrict_collection_access_refuse_de_verrouiller_par_defaut():
    """Le défaut était [] = "aucun groupe autorisé" : un appel sans argument
    coupait l'accès à la collection pour TOUS les groupes."""
    c = Client({})
    with pytest.raises(ValueError, match="authorized_group_ids est obligatoire"):
        c.restrict_collection_access(collection_id=14115)
    assert c._http.calls == [], "aucune écriture ne doit partir"


def test_restrict_collection_access_accepte_un_verrouillage_explicite():
    graphe = {"groups": {"1": {}, "2": {}}}
    c = Client({
        ("GET", "/api/collection/graph"): FakeResponse(200, graphe),
        ("PUT", "/api/collection/graph"): FakeResponse(200, {}),
    })
    c.restrict_collection_access(collection_id=14115, authorized_group_ids=[1])
    envoye = [x for x in c._http.calls if x[0] == "PUT"][0][2]
    assert envoye["groups"]["2"]["14115"] == "none"
    assert "14115" not in envoye["groups"]["1"], "le groupe autorisé n'est pas touché"


def test_filtre_introuvable_leve_au_lieu_d_ecrire():
    """Le garde-fou était branché sur `verbose`. En mode par défaut, un filtre
    introuvable tombait dans le else et le PUT partait quand même."""
    c = Client({("GET", "/api/card/7"): FakeResponse(200, {"parameters": [{"name": "Autre"}]})})
    with pytest.raises(ValueError, match="Aucun filtre"):
        c.restrict_filter_with_card_values(
            item_type="card", item_id=7, filter_name="Client",
            card_id=1, card_column_name="client")
    assert not any(x[0] == "PUT" for x in c._http.calls), "rien ne doit être écrit"


def test_filtre_trouve_est_bien_recable():
    item = {"parameters": [{"name": "Client"}]}
    c = Client({
        ("GET", "/api/card/7"): FakeResponse(200, item),
        ("PUT", "/api/card/7"): FakeResponse(200, {}),
    })
    c.restrict_filter_with_card_values(
        item_type="card", item_id=7, filter_name="Client",
        card_id=99, card_column_name="client")
    envoye = [x for x in c._http.calls if x[0] == "PUT"][0][2]
    param = envoye["parameters"][0]
    assert param["values_source_type"] == "card"
    assert param["values_source_config"]["card_id"] == 99
    assert param["values_source_config"]["value_field"][1] == "CLIENT"
