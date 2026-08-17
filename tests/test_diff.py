"""Tests du différentiel avant/après. Hors-ligne, aucun appel réseau.

Repris de l'ancien test_validate.py : seuls les tests des fonctions conservées
sont portés. Les 18 autres testaient check_structure (cassé depuis MBQL5),
check_refs (remplacé par le graphe natif) et les CardUnit couplés au bloc IaC.
"""

from spark_metabase_api import diff as D


def test_report_collects_and_renders():
    r = D.Report()
    r.add(D.Finding("c/A", "structure", "ok", "well-formed"))
    r.add(D.Finding("c/B", "execution", "error", "query failed: boom"))
    assert [f.level for f in r.findings] == ["ok", "error"]
    assert r.ok() is False
    assert len(r.errors()) == 1
    assert r.exit_code() == 1
    out = r.render()
    assert "c/B" in out and "query failed" in out
    assert "1 error" in r.summary()


def test_check_differential():
    before = [{"k": "a", "v": 10}, {"k": "b", "v": 20}]
    same = [{"k": "a", "v": 10}, {"k": "b", "v": 20}]
    assert all(f.level == "ok" for f in D.check_differential("t", before, same, mode="identical"))

    dropped = [{"k": "a", "v": 10}]
    fs = D.check_differential("t", before, dropped, mode="identical")
    assert any(f.level == "error" and "row count" in f.message for f in fs)

    drift = [{"k": "a", "v": 10}, {"k": "b", "v": 25}]
    fs = D.check_differential("t", before, drift, mode="monitor")
    assert any(f.level == "warn" and "sum(v)" in f.message for f in fs)
    fs2 = D.check_differential("t", before, drift, mode="identical")
    assert any(f.level == "error" for f in fs2)


def test_differential_identical_numeric_to_null():
    """Une colonne numérique qui passe tout-NULL, à nom et compte de lignes
    identiques, reste un écart en mode identical."""
    before = [{"id": 1, "amount": 100}, {"id": 2, "amount": 200}]
    after = [{"id": 1, "amount": None}, {"id": 2, "amount": None}]
    fs = D.check_differential("c/rev", before, after, mode="identical")
    assert any(f.level == "error" for f in fs), \
        "numeric->all-null doit être une erreur en mode identical, obtenu {}".format(
            [f.message for f in fs])


def test_differential_identical_numeric_to_string():
    """Une colonne numérique qui devient une chaîne est un écart en mode identical."""
    before = [{"revenue": 100, "name": "x"}]
    after = [{"revenue": "N/A", "name": "x"}]
    fs = D.check_differential("t", before, after, mode="identical")
    assert any(f.level == "error" for f in fs)


def test_check_values():
    # égalité de multiset, insensible à l'ordre
    assert all(f.level == "ok" for f in D.check_values("t", [1.0, 2.0], [2.0, 1.0], mode="identical"))
    # longueurs différentes -> finding
    assert any(f.level == "error" for f in D.check_values("t", [1.0], [1.0, 2.0], mode="identical"))
    # dérive numérique au-delà de la tolérance
    drift = D.check_values("t", [10.0, 20.0], [10.0, 25.0], mode="identical")
    assert any(f.level == "error" and "differ" in f.message for f in drift)
    # dans la tolérance -> ok
    assert all(f.level == "ok" for f in D.check_values("t", [100.0], [100.05], mode="monitor", tolerance=0.001))
    # mode monitor -> warn
    assert any(f.level == "warn" for f in D.check_values("t", [100.0], [200.0], mode="monitor"))
    # comparaison exacte pour du non numérique
    assert any(f.level == "error" for f in D.check_values("t", ["a", "b"], ["a", "c"], mode="identical"))


def test_check_values_matches_exact_inequality():
    """La migration conv s'appuie sur : check_values(identical) erre SI ET SEULEMENT SI
    before != after, pour les listes numériques triées que produit card_values."""
    cases = [([1.0, 2.0], [1.0, 2.0]), ([1.0, 2.0], [2.0, 1.0]), ([1.0, 2.0], [1.0, 3.0]),
             ([1.0], [1.0, 2.0]), ([1.0, 2.0, 3.0], [1.0, 2.0]), ([], [])]
    for b, a in cases:
        bs, as_ = sorted(b), sorted(a)
        errored = any(f.level == "error" for f in D.check_values("t", bs, as_, mode="identical"))
        assert errored == (bs != as_), "écart pour {} vs {}".format(bs, as_)


def test_validate_shim_still_serves_the_active_campaigns():
    """Les 3 scripts de campagne active font `from spark_metabase_api import validate as V`
    puis `V.check_values(...)`. Ce chemin doit rester vivant jusqu'à leur migration."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from spark_metabase_api import validate as V
    assert V.check_values is D.check_values
    assert V.check_differential is D.check_differential
    assert V.Finding is D.Finding
    assert all(f.level == "ok" for f in V.check_values("t", [1.0], [1.0], mode="identical"))
