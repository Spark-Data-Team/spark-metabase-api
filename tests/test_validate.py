from spark_metabase_api import validate as V

def test_report_collects_and_renders():
    r = V.Report()
    r.add(V.Finding("c/A", "structure", "ok", "well-formed"))
    r.add(V.Finding("c/B", "execution", "error", "query failed: boom"))
    assert [f.level for f in r.findings] == ["ok", "error"]
    assert r.ok() is False
    assert len(r.errors()) == 1
    assert r.exit_code() == 1
    out = r.render()
    assert "c/B" in out and "query failed" in out
    assert "1 error" in r.summary()


def test_units_from_spec_and_payload():
    from spark_metabase_api import iac
    spec = iac.spec_from_dict({
        "name": "Acme",
        "cards": [{"name": "Rev", "definition": {
            "dataset_query": {"database": 2, "type": "native",
                              "native": {"query": "SELECT 1"}},
            "display": "table"}}],
    })
    units = V.units_from_spec(spec)
    assert len(units) == 1
    assert units[0].target == "Acme/Rev"
    assert units[0].dataset_query["database"] == 2
    assert units[0].live_card_id is None

    u = V.unit_from_payload("c/X", {"dataset_query": {"database": 1, "type": "query",
                                                      "query": {"source-table": 5}}})
    assert u.dataset_query["type"] == "query"

class FakeClient:
    def __init__(self, cards): self._cards = cards
    def get(self, ep, *a, **k):
        cid = int(ep.rstrip("/").split("/")[-1])
        return self._cards.get(cid, False)

def test_unit_from_card_id():
    client = FakeClient({7: {"dataset_query": {"database": 1, "type": "native",
                                               "native": {"query": "SELECT 1"}},
                             "display": "scalar"}})
    u = V.unit_from_card_id(client, 7)
    assert u.live_card_id == 7 and u.dataset_query["database"] == 1


def test_check_structure():
    ok = V.CardUnit("c/A", {"database": 1, "type": "native", "native": {"query": "SELECT 1"}})
    assert V.check_structure(ok).level == "ok"
    no_db = V.CardUnit("c/B", {"type": "native", "native": {"query": "SELECT 1"}})
    assert V.check_structure(no_db).level == "error"
    empty = V.CardUnit("c/C", {"database": 1, "type": "native", "native": {"query": ""}})
    assert V.check_structure(empty).level == "error"
    bad_type = V.CardUnit("c/D", {"database": 1, "type": "weird"})
    assert V.check_structure(bad_type).level == "error"


def test_check_refs():
    client = FakeClient({9: {"archived": False}})  # card 9 exists; 99 does not
    src_ok = V.CardUnit("c/A", {"database": 1, "type": "query",
                                "query": {"source-table": "card__9"}})
    assert all(f.level != "error" for f in V.check_refs(client, src_ok))
    src_bad = V.CardUnit("c/B", {"database": 1, "type": "query",
                                 "query": {"source-table": "card__99"}})
    assert any(f.level == "error" for f in V.check_refs(client, src_bad))
    ff_bad = V.CardUnit("c/C", {"database": 1, "type": "native", "native": {
        "query": "SELECT 1", "template-tags": {
            "x": {"values_source_config": {"card_id": 99}}}}})
    assert any(f.level == "error" for f in V.check_refs(client, ff_bad))


class ExecClient:
    def __init__(self, dataset_result=None, card_rows=None):
        self._ds = dataset_result; self._rows = card_rows
    def run_query(self, dq, parameters=None): return self._ds
    def get_card_data(self, card_id=None, data_format="json"): return self._rows

def test_check_execution():
    good = ExecClient(dataset_result={"status": "completed",
        "data": {"cols": [{"name": "n"}], "rows": [[1], [2]]}})
    u = V.CardUnit("c/A", {"database": 1, "type": "native", "native": {"query": "SELECT n"}})
    f = V.check_execution(good, u)
    assert f.level == "ok" and "2 rows" in f.message

    failed = ExecClient(dataset_result={"status": "failed", "error": "SQL compilation error"})
    assert V.check_execution(failed, u).level == "error"

    empty = ExecClient(dataset_result={"status": "completed", "data": {"cols": [], "rows": []}})
    assert V.check_execution(empty, u).level == "warn"

    saved = ExecClient(card_rows=[{"n": 1}])
    su = V.CardUnit("card#5", {"database": 1, "type": "native", "native": {"query": "x"}}, live_card_id=5)
    assert V.check_execution(saved, su).level == "ok"


# FIX 1: saved-card path must detect query failure (dict result, not list)
def test_check_execution_saved_card_failure():
    """get_card_data returning a dict (failed query) must surface as an error, not ok."""
    class FailedCardClient:
        def get_card_data(self, card_id=None, data_format="json"):
            return {"status": "failed", "error": "SQL compilation error"}
    su = V.CardUnit("card#5", {"database": 1, "type": "native", "native": {"query": "x"}}, live_card_id=5)
    f = V.check_execution(FailedCardClient(), su)
    assert f.level == "error", "expected error level, got {!r}".format(f.level)
    assert "SQL compilation error" in f.message, "expected error text in message: {!r}".format(f.message)


# FIX 2: check_refs must not raise on malformed source-table refs
def test_check_refs_malformed_source_table():
    """Malformed 'card__abc' ref must emit a refs error, not raise ValueError/IndexError."""
    client = FakeClient({})
    unit = V.CardUnit("c/X", {"database": 1, "type": "query",
                               "query": {"source-table": "card__abc"}})
    findings = V.check_refs(client, unit)
    assert any(f.level == "error" and "refs" == f.check for f in findings), \
        "expected a refs error finding for malformed ref"


def test_check_differential():
    before = [{"k": "a", "v": 10}, {"k": "b", "v": 20}]
    same = [{"k": "a", "v": 10}, {"k": "b", "v": 20}]
    assert all(f.level == "ok" for f in V.check_differential("t", before, same, mode="identical"))

    dropped = [{"k": "a", "v": 10}]
    fs = V.check_differential("t", before, dropped, mode="identical")
    assert any(f.level == "error" and "row count" in f.message for f in fs)

    drift = [{"k": "a", "v": 10}, {"k": "b", "v": 25}]
    fs = V.check_differential("t", before, drift, mode="monitor")
    assert any(f.level == "warn" and "sum(v)" in f.message for f in fs)
    fs2 = V.check_differential("t", before, drift, mode="identical")
    assert any(f.level == "error" for f in fs2)


def test_gate_and_guarded_apply():
    # gate: a structurally broken unit short-circuits (no execution attempted)
    broken = V.CardUnit("c/bad", {"type": "native", "native": {"query": "x"}})
    g = V.gate(ExecClient(), [broken], execute=True)
    assert not g.ok() and [f.check for f in g.findings] == ["structure"]

    # guarded_apply: gate errors -> mutate_fn NOT called
    calls = []
    rep = V.guarded_apply(ExecClient(), [broken], lambda: calls.append(1),
                          differential="off", force=False, execute=False)
    assert calls == [] and not rep.ok()

    # force=True runs mutate_fn despite errors
    calls2 = []
    V.guarded_apply(ExecClient(), [broken], lambda: calls2.append(1),
                    differential="off", force=True, execute=False)
    assert calls2 == [1]


def test_resolve_cli_target_spec(tmp_path):
    from spark_metabase_api import iac, validate as V
    spec_file = tmp_path / "s.json"
    iac.dump(iac.spec_from_dict({"name": "Acme", "cards": [{"name": "R",
        "definition": {"dataset_query": {"database": 1, "type": "native",
                                         "native": {"query": "SELECT 1"}}}}]}), str(spec_file))
    units = V.resolve_cli_target(object(), str(spec_file))
    assert len(units) == 1 and units[0].target == "Acme/R"

def test_resolve_cli_target_card_id():
    from spark_metabase_api import validate as V
    client = FakeClient({4: {"dataset_query": {"database": 1, "type": "native",
                                               "native": {"query": "x"}}}})
    units = V.resolve_cli_target(client, "4")
    assert units[0].live_card_id == 4


# FIX 3a: guarded_apply differential path
def test_guarded_apply_differential_monitor():
    """guarded_apply with differential='monitor' emits a warn finding when results change."""
    call_count = {"n": 0}
    baseline_rows = [{"v": 10}]
    after_rows = [{"v": 20}]

    class DiffClient:
        def get(self, ep, *a, **k):
            return {"archived": False}
        def get_card_data(self, card_id=None, data_format="json"):
            # first call: baseline; second call (post-mutate): different
            call_count["n"] += 1
            if call_count["n"] == 1:
                return baseline_rows
            return after_rows
        def run_query(self, dq, parameters=None):
            return {"status": "completed", "data": {"cols": [{"name": "v"}], "rows": [[10]]}}

    # A live unit with a well-formed dataset_query so structure/refs/execution all pass
    live_unit = V.CardUnit(
        target="c/A",
        dataset_query={"database": 1, "type": "native", "native": {"query": "SELECT v"}},
        live_card_id=42,
    )

    mutated = []
    report = V.guarded_apply(
        DiffClient(),
        [live_unit],
        lambda: mutated.append(1),
        differential="monitor",
        execute=True,
    )

    assert mutated == [1], "mutate_fn should have been called"
    diff_findings = [f for f in report.findings if f.check == "differential"]
    assert diff_findings, "expected differential findings"
    assert any(f.level == "warn" for f in diff_findings), \
        "expected a warn in monitor mode for changed results"


# FIX 3b: iac.apply(validate=True) happy path
def test_iac_apply_validate_happy_path(monkeypatch):
    """iac.apply(validate=True) with a clean spec calls _execute_collection (no ValidationError)."""
    from spark_metabase_api import iac, validate as V

    spec = iac.spec_from_dict({"name": "Clean", "cards": [{"name": "Card1", "definition": {
        "dataset_query": {"database": 1, "type": "native", "native": {"query": "SELECT 1"}},
        "display": "scalar",
    }}]})

    # Client that passes execution gate
    class HappyClient:
        def get(self, ep, *a, **k):
            return {"archived": False}
        def run_query(self, dq, parameters=None):
            return {"status": "completed",
                    "data": {"cols": [{"name": "n"}], "rows": [[1]]}}

    called = {"executed": False}
    monkeypatch.setattr(iac, "plan", lambda *a, **k: iac.Plan())
    monkeypatch.setattr(iac, "_execute_collection",
                        lambda *a, **k: called.__setitem__("executed", True))

    # Should NOT raise; gate passes cleanly
    iac.apply(HappyClient(), spec, validate=True)
    assert called["executed"] is True, "_execute_collection should have been called"


def test_iac_apply_gate_aborts(monkeypatch):
    from spark_metabase_api import iac, validate as V
    spec = iac.spec_from_dict({"name": "Acme", "cards": [{"name": "Bad",
        "definition": {"dataset_query": {"type": "native", "native": {"query": "x"}}}}]})  # no database -> structure error

    called = {"executed": False}
    monkeypatch.setattr(iac, "_execute_collection",
                        lambda *a, **k: called.__setitem__("executed", True))
    monkeypatch.setattr(iac, "plan", lambda *a, **k: iac.Plan())

    try:
        iac.apply(object(), spec, validate=True)
        assert False, "expected ValidationError"
    except V.ValidationError:
        pass
    assert called["executed"] is False  # gate aborted before mutation
