import pytest

from scripts import create_channel_internal_dashboard as module
from scripts.create_channel_internal_dashboard import (
    CARTES, GRILLE, NB_CARTES_V1, PARAMETRES, base, controler, rollback, tags_natifs, verifier_grille)


def test_grille_sans_chevauchement():
    verifier_grille(GRILLE)


def test_grille_refuse_un_chevauchement():
    with pytest.raises(ValueError):
        verifier_grille([("Lead", 1, 0, 0, 12, 3), ("Lead", 2, 0, 6, 12, 3)])


def test_meme_case_sur_deux_onglets_autorisee():
    verifier_grille([("Lead", 1, 0, 0, 12, 3), ("Ecom", 2, 0, 0, 12, 3)])


def test_grille_refuse_un_debordement():
    with pytest.raises(ValueError):
        verifier_grille([("Lead", 1, 0, 20, 8, 3)])


def test_grille_refuse_un_onglet_inconnu():
    with pytest.raises(ValueError):
        verifier_grille([("Autre", 1, 0, 0, 8, 3)])


def test_chaque_carte_neuve_est_posee_une_fois():
    neuves = [ref for _o, ref, *_ in GRILLE if isinstance(ref, str) and ref.startswith("neuf:")]
    assert sorted(neuves, key=lambda r: int(r.split(":")[1])) == ["neuf:{}".format(i) for i in range(len(CARTES))]


def test_cartes_v1_gardent_leur_place():
    # --split retrouve 57576-57580 par position.
    assert [c[0] for c in CARTES[:NB_CARTES_V1]] == [
        "Performance by client (all clients)", "Cost by client by date (all clients)",
        "CPC by client by date (all clients)", "CTR by client by date (all clients)",
        "CPM by client by date (all clients)"]


def test_onglet_general_sans_conversion():
    # Colonnes du SELECT final, entre le dernier « select » et « from base ».
    sql = CARTES[0][1].lower()
    fin = sql.rfind("from base")
    colonnes = sql[sql.rfind("select", 0, fin):fin]
    assert "cost" in colonnes
    assert "leads" not in colonnes and "purchases" not in colonnes


def test_modele_filtre_par_sous_requete():
    assert "model = 'lead generation'" in base("lead")
    assert "model = 'e-commerce'" in base("ecom")
    assert "client_categories" not in base()
    assert "{modele}" not in base() and "{{channel}}" in base()


def test_tags_natifs_couvrent_les_filtres():
    tags = tags_natifs()
    for _slug, _nom, _type, _defaut, tag in PARAMETRES:
        assert tag in tags
    assert tags["time_periods"]["type"] == "temporal-unit"


class FauxHttp:
    def __init__(self, reponse=None):
        self.appels, self.reponse = [], reponse

    def put(self, _mb, chemin, json):
        self.appels.append(chemin)

    def post(self, _mb, chemin, json):
        return self.reponse


def test_rollback_sans_dashboard_archive_seulement_les_cartes(monkeypatch):
    faux = FauxHttp()
    monkeypatch.setattr(module, "http", faux)
    rollback(None, None, [57700, 57701])
    assert faux.appels == ["/api/card/57700", "/api/card/57701"]


def dashboard_une_tuile():
    params = [{"slug": s, "id": s, "type": "x", "default": None} for s in ("date_filter", "time_period", "channel")]
    return {"id": 1, "parameters": params, "dashcards": [{"id": 2, "card_id": 3, "card": {"name": "carte"}}]}


@pytest.mark.parametrize("reponse", [{"status": "failed", "error": "boom"},
                                     {"status": "completed", "data": {"rows": []}}])
def test_controler_leve_si_tuile_vide_ou_en_erreur(monkeypatch, reponse):
    monkeypatch.setattr(module, "http", FauxHttp(reponse))
    with pytest.raises(RuntimeError):
        controler(None, dashboard_une_tuile())


def test_controler_passe_si_tuile_remplie(monkeypatch):
    monkeypatch.setattr(module, "http", FauxHttp({"status": "completed", "data": {"rows": [[1]]}}))
    controler(None, dashboard_une_tuile())
