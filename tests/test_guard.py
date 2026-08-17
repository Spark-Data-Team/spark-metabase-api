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
    assert "NON touché" in msgs
    assert "5 NON touché(s)" in msgs, "le compte d'objets intacts doit être juste"
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


# --- Corrections issues de la revue de code (2026-08-17) ---

def test_le_snapshot_n_ecrase_jamais_un_snapshot_existant(tmp_path):
    """Le nom était {etiquette}-{kind}-{len(ids)}.json, donc relancer un lot
    après un échec réécrivait le snapshot d'AVANT mutation avec l'état DÉJÀ
    muté. Le rollback restaurait alors les dégâts."""
    c = _client()
    a = guard.snapshot(c, "card", [1, 2], dossier=str(tmp_path))
    b = guard.snapshot(c, "card", [1, 2], dossier=str(tmp_path))
    assert a != b, "deux snapshots du même lot doivent avoir des noms distincts"
    assert len(list(tmp_path.glob("*.json"))) == 2, \
        "le second ne doit pas avoir écrasé le premier"


def test_le_snapshot_refuse_d_ecraser_un_fichier_existant(tmp_path, monkeypatch):
    """Même avec un horodatage figé, l'écrasement est refusé plutôt que subi."""
    c = _client()
    monkeypatch.setattr(guard, "_horodatage", lambda: "FIGE")
    guard.snapshot(c, "card", [1, 2], dossier=str(tmp_path))
    with pytest.raises(FileExistsError, match="Refus d'écraser"):
        guard.snapshot(c, "card", [1, 2], dossier=str(tmp_path))


def test_restore_avec_une_liste_vide_ne_restaure_rien(tmp_path):
    """`ids=[]` est l'appel naturel après un lot sans échec. Le test `if ids`
    le confondait avec None et réécrivait TOUS les objets du snapshot."""
    c = _client()
    chemin = guard.snapshot(c, "card", [1, 2, 3], dossier=str(tmp_path))
    c._http.calls.clear()
    assert guard.restore(c, chemin, ids=[]) == []
    assert not any(x[0] == "PUT" for x in c._http.calls), "aucune écriture ne doit partir"


def test_restore_sans_ids_restaure_tout(tmp_path):
    c = _client()
    chemin = guard.snapshot(c, "card", [1, 2, 3], dossier=str(tmp_path))
    c._http.calls.clear()
    assert sorted(guard.restore(c, chemin)) == [1, 2, 3]


def test_restore_verifie_la_relecture(tmp_path):
    """restore faisait un http.put nu, sans relecture : une restauration
    partiellement rejetée était rapportée comme réussie."""
    c = _client()
    chemin = guard.snapshot(c, "card", [1], dossier=str(tmp_path))
    # la relecture rend autre chose que ce qui a été restauré
    c._http.routes[("GET", "/api/card/1?legacy-mbql=true")] = FakeResponse(
        200, {"id": 1, "name": "AUTRE CHOSE"})
    with pytest.raises(ValueError, match="champ 'name'"):
        guard.restore(c, chemin)


def test_un_echec_dans_le_lot_ne_finit_pas_sur_un_ok(tmp_path):
    """Le retour de _appliquer était ignoré pour la phase lot : le rapport se
    terminait sur une ligne ok et ne donnait pas la commande de rollback."""
    c = _client(n=6)

    def muter(cl, i):
        if i == 5:
            raise RuntimeError("boom")

    rap = guard.batch(c, [1, 2, 3, 4, 5, 6], muter=muter, dry_run=False,
                      echantillon=2, dossier=str(tmp_path))
    assert not rap.ok()
    dernier = rap.findings[-1]
    assert dernier.level == "error", "le rapport ne doit pas finir sur un ok"
    assert "guard.restore" in dernier.message


def test_le_dossier_par_defaut_ne_depend_pas_du_cwd():
    """_DOSSIER_DEFAUT était relatif : un script lancé depuis scripts/ écrivait
    ses snapshots dans scripts/migration/, invisible pour l'opérateur."""
    import pathlib as _pl
    assert _pl.Path(guard._DOSSIER_DEFAUT).is_absolute()
    assert _pl.Path(guard._DOSSIER_DEFAUT).name == "migration"


# --- Passe adversariale (2026-08-17) : refutation des corrections ---

def test_restore_d_un_dashboard_ne_bute_pas_sur_les_champs_volatils(tmp_path):
    """La correction précédente passait l'objet COMPLET du snapshot à
    put_dashboard, qui compare chaque champ relu. updated_at et view_count sont
    rafraîchis par Metabase à chaque PUT, donc le rollback échouait TOUJOURS,
    et sur un snapshot de N dashboards il s'arrêtait après le premier."""
    complet = {"id": 7, "name": "D", "tabs": [], "parameters": [], "dashcards": [],
               "updated_at": "T1", "view_count": 10, "can_write": True,
               "last-edit-info": {"timestamp": "T1"}}
    apres_put = dict(complet, updated_at="T4", view_count=11)
    c = FakeClient({("PUT", "/api/dashboard/7"): FakeResponse(200, {})})
    appels = {"n": 0}

    def get_dash(n):
        appels["n"] += 1
        return FakeResponse(200, complet if appels["n"] <= 2 else apres_put)

    c._http.routes[("GET", "/api/dashboard/7")] = get_dash
    chemin = guard.snapshot(c, "dashboard", [7], dossier=str(tmp_path))
    assert guard.restore(c, chemin) == [7]

    envoye = [x for x in c._http.calls if x[0] == "PUT"][0][2]
    assert "updated_at" not in envoye, "un champ en lecture seule ne doit pas être renvoyé"
    assert "view_count" not in envoye
    assert "can_write" not in envoye
    assert envoye["name"] == "D", "les champs réinscriptibles doivent l'être"


def test_une_mesure_vide_des_deux_cotes_est_signalee(tmp_path):
    """Une carte à colonnes uniquement textuelles mesure [] avant et après, donc
    check_values dit 'ok' sans rien avoir comparé."""
    c = _client(n=2)
    rap = guard.batch(c, [1, 2], muter=lambda cl, i: None, mesurer=lambda cl, i: [],
                      mode="identical", dry_run=False, dossier=str(tmp_path))
    avertissements = [f for f in rap.findings if f.check == "mesure" and f.level == "warn"]
    assert len(avertissements) == 2
    assert "ne prouve rien" in avertissements[0].message
