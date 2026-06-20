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
