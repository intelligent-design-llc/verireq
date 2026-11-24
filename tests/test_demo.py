"""One path through the fictional DemoSat project: analyse, closure, and the three exports."""
from fastapi.testclient import TestClient

from verireq.app import app
from verireq.reqif import loads
from verireq.xray_connector import import_results


def test_demo_project_covers_every_module_and_export():
    client = TestClient(app)
    config = client.get("/api/config")
    assert config.status_code == 200
    cfg = config.json()
    assert cfg["llm"]["enabled"] is False
    assert cfg["jira"]["enabled"] is False
    demo = client.get("/api/demo")
    assert demo.status_code == 200
    body = demo.json()
    count = body["summary"]["requirements"]
    assert 40 <= count <= 60
    assert body["profile"]["id"] == "nasa"
    assert body["summary"]["closure"]["closed"] >= 1
    assert body["source"] == "DemoSat sample project"
    findings = [f["rule_id"] for row in body["requirements"] for f in row["findings"]]
    assert "DOC-02" in findings
    assert "CON-02" in findings
    trace = [f["rule_id"] for f in body["trace"]["findings"]]
    assert "TRACE-02" in trace
    assert "TRACE-03" in trace
    assert body["insight"]["disagreements"] >= 1
    ids = {row["id"] for row in body["requirements"]}
    assert any(row["parent_id"] in ids for row in body["requirements"])
    assert any(row["depends_on"] for row in body["requirements"])
    assert any(row["evidence"] and row["verification_status"] == "Passed" for row in body["requirements"])
    methods = {m["name"] for m in body["profile"]["verification_methods"]}
    assert methods == {"Test", "Analysis", "Inspection", "Demonstration"}

    workbook = client.post("/api/export", json=body)
    assert workbook.status_code == 200 and workbook.content[:2] == b"PK"
    reqif = client.post("/api/reqif", json=body)
    assert reqif.status_code == 200
    again = loads(reqif.content)
    assert {r.id for r in again} == ids
    linked = next(r for r in again if r.id == "DS-EPS-020")
    assert linked.parent_id == "DS-MIS-010"
    xray = client.post("/api/xray/export", json=body)
    assert xray.status_code == 200
    updates = import_results(xray.text, "demosat.json")
    assert {u["req_id"] for u in updates} == ids
    junit = client.post("/api/xray/export-junit", json=body)
    assert junit.status_code == 200 and import_results(junit.text, "demosat.xml")
