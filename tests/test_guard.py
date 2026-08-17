"""Tests des écritures de masse gardées. Hors-ligne, snapshots en tmp_path."""

import json

import pytest

from spark_metabase_api import guard
from tests.test_core import FakeClient, FakeResponse


def _client(n=3):
    routes = {}
    for i in range(1, n + 1):
        routes[("GET", "/api/card/{}?legacy-mbql=true".format(i))] = FakeResponse(
            200, {"id": i, "name": "carte {}".format(i)})
        routes[("PUT", "/api/card/{}".format(i))] = FakeResponse(200, {})
    return FakeClient(routes)


def test_dry_run_ne_touche_a_rien_mais_sauvegarde(tmp_path):
    c = _client()
    rap = guard.batch(c, [1, 2, 3], muter=lambda cl, i: 1 / 0, dossier=str(tmp_path))
    assert rap.ok()
    assert not any(x[0] == "PUT" for x in c._http.calls), "aucune écriture en dry-run"
    fichiers = list(tmp_path.glob("*.json"))
    assert len(fichiers) == 1
    assert json.loads(fichiers[0].read_text())["etat"]["1"]["name"] == "carte 1"


def test_le_snapshot_precede_toute_mutation(tmp_path):
    """Sans snapshot préalable, il n'y a pas de rollback possible."""
    from spark_metabase_api import http

    c = _client()
    guard.batch(c, [1], muter=lambda cl, i: http.put(cl, "/api/card/1", json={}),
                dry_run=False, dossier=str(tmp_path))
    methodes = [x[0] for x in c._http.calls]
    assert methodes.index("GET") < methodes.index("PUT")


def test_un_echec_sur_l_echantillon_arrete_le_lot(tmp_path):
    """Le reste des objets ne doit PAS être touché."""
    c = _client(n=6)
    vus = []

    def muter(cl, i):
        vus.append(i)
        if i == 2:
            raise RuntimeError("boom")

    rap = guard.batch(c, [1, 2, 3, 4, 5, 6], muter=muter, dry_run=False,
                      echantillon=3, dossier=str(tmp_path))
    assert vus == [1, 2], "on s'arrête à l'objet fautif"
    assert not rap.ok()
    msgs = " ".join(f.message for f in rap.findings)
    assert "n'ont PAS été touchés" in msgs
    assert "guard.restore" in msgs, "le message doit donner la commande de rollback"


def test_le_differentiel_identical_arrete_le_lot(tmp_path):
    """Un refacto qui change les nombres doit stopper avant de propager."""
    c = _client(n=5)
    mesures = {1: ([10.0], [10.0]), 2: ([20.0], [99.0])}
    etat = {}

    def mesurer(cl, i):
        avant, apres = mesures.get(i, ([1.0], [1.0]))
        pris = etat.get(i, 0)
        etat[i] = pris + 1
        return avant if pris == 0 else apres

    rap = guard.batch(c, [1, 2, 3, 4, 5], muter=lambda cl, i: None, mesurer=mesurer,
                      mode="identical", dry_run=False, echantillon=3, dossier=str(tmp_path))
    assert not rap.ok()
    assert any(f.level == "error" and "values" == f.check for f in rap.findings)


def test_le_lot_complet_passe_quand_tout_va_bien(tmp_path):
    c = _client(n=5)
    vus = []
    rap = guard.batch(c, [1, 2, 3, 4, 5], muter=lambda cl, i: vus.append(i),
                      dry_run=False, echantillon=2, dossier=str(tmp_path))
    assert vus == [1, 2, 3, 4, 5]
    assert rap.ok()


def test_restore_reecrit_l_etat_sauvegarde(tmp_path):
    c = _client()
    chemin = guard.snapshot(c, "card", [1, 2], dossier=str(tmp_path))
    c._http.calls.clear()
    faits = guard.restore(c, chemin)
    assert sorted(faits) == [1, 2]
    puts = [x for x in c._http.calls if x[0] == "PUT"]
    assert len(puts) == 2
    assert puts[0][2]["name"] == "carte 1"


def test_restore_refuse_un_id_absent_du_snapshot(tmp_path):
    c = _client()
    chemin = guard.snapshot(c, "card", [1], dossier=str(tmp_path))
    with pytest.raises(ValueError, match="absent du snapshot"):
        guard.restore(c, chemin, ids=[99])


def test_kind_inconnu_est_refuse():
    with pytest.raises(ValueError, match="kind doit être"):
        guard.snapshot(_client(), "widget", [1])
