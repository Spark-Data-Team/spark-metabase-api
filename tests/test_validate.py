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
