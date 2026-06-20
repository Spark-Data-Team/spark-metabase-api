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
