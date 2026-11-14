"""ReqIF, trace, closure, Jira, and Xray. Jira uses a fake HTTP client."""
import json
from pathlib import Path

import httpx
import pytest

from verireq.closure import closure_state, summarize
from verireq.core import analyse
from verireq.jira_connector import JiraError, config as jira_config, map_status, pull_statuses, push_requirements
from verireq.models import Requirement
from verireq.reqif import dumps, loads
from verireq.trace import trace_findings
from verireq.xray_connector import export_execution, export_junit, import_results

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_reqif_round_trip_keeps_text_and_links():
    reqs = [
        Requirement("SYS-010", "The bus shall provide 28 V within 0.5 V.", verification_status="Planned"),
        Requirement("SYS-011", "The bus shall shed load within 2 s.", parent_id="SYS-010",
                    depends_on=["SYS-010"], evidence="RPT-14", verification_status="Passed",
                    method_override="Test"),
        Requirement("SYS-012", "The radio shall transmit at 4 kbps.", parent_id="SYS-010"),
    ]
    again = loads(dumps(reqs, title="Round trip"))
    assert [(r.id, r.text, r.parent_id, r.depends_on, r.verification_status, r.method_override) for r in again] == [
        ("SYS-010", reqs[0].text, "", [], "Planned", ""),
        ("SYS-011", reqs[1].text, "SYS-010", ["SYS-010"], "Passed", "Test"),
        ("SYS-012", reqs[2].text, "SYS-010", [], "Not started", ""),
    ]
    xml = dumps(reqs).decode("utf-8")
    assert "REQ-IF-VERSION" in xml and "1.1" in xml
    assert "ReqIF.Text" in xml and "Parent" in xml and "Depends On" in xml


def test_trace_orphans_and_broken_links():
    reqs = [
        Requirement("SYS-010", "The bus shall provide 28 V."),
        Requirement("SYS-011", "The battery shall charge.", parent_id="SYS-010"),
        Requirement("SYS-012", "The radio shall transmit.", depends_on=["SYS-099"]),
        Requirement("SYS-013", "The camera shall image."),
    ]
    rules = {(f.req_id, f.rule_id) for f in trace_findings(reqs)}
    assert ("SYS-012", "TRACE-02") in rules
    assert ("SYS-013", "TRACE-03") in rules
    assert ("SYS-010", "TRACE-03") not in rules
    assert trace_findings([Requirement("A-1", "The bus shall provide 5 V.")]) == []


def test_closure_needs_status_and_evidence():
    assert closure_state("Passed", "") == "Evidence missing"
    assert closure_state("Passed", "RPT-1") == "Closed"
    assert closure_state("Waived", "waiver W-2") == "Closed"
    assert closure_state("Failed", "RPT-9") == "Failed"
    assert closure_state("In progress", "") == "In progress"
    assert closure_state("Not started", "") == "Open"
    summary = summarize([
        {"verification_status": "Passed", "evidence": "RPT-1"},
        {"verification_status": "Passed", "evidence": ""},
    ])
    assert summary["closed"] == 1 and summary["total"] == 2


def test_jira_off_by_default_and_push_pull_with_fake_client(monkeypatch):
    for key in ("JIRA_BASE_URL", "JIRA_API_TOKEN", "JIRA_PROJECT_KEY", "JIRA_EMAIL"):
        monkeypatch.delenv(key, raising=False)
    assert jira_config()["enabled"] is False
    with pytest.raises(JiraError):
        push_requirements([Requirement("SYS-010", "The bus shall provide 28 V.")])

    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret-token")
    monkeypatch.setenv("JIRA_PROJECT_KEY", "DEMO")
    seen = {}

    class Fake:
        def post(self, url, json=None):
            seen["url"] = url
            seen["body"] = json
            seen["token_in_body"] = "secret-token" in str(json)
            request = httpx.Request("POST", url)
            return httpx.Response(201, json={"key": "DEMO-12", "id": "10012"}, request=request)

        def get(self, url, params=None):
            request = httpx.Request("GET", url)
            return httpx.Response(200, json={"fields": {
                "summary": "SYS-010",
                "status": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}},
            }}, request=request)

        def close(self):
            pass

    created = push_requirements([Requirement("SYS-010", "The bus shall provide 28 V within 0.5 V.")], client=Fake())
    assert created == [{"req_id": "SYS-010", "key": "DEMO-12", "id": "10012"}]
    assert seen["url"].endswith("/rest/api/3/issue")
    assert seen["body"]["fields"]["project"]["key"] == "DEMO"
    assert seen["token_in_body"] is False
    pulled = pull_statuses(["DEMO-12"], client=Fake())
    assert pulled[0]["verification_status"] == "In progress"
    assert map_status("Done", "done") == "Passed"
    public = jira_config()
    assert public["enabled"] is True and "secret-token" not in json.dumps(public)


def test_xray_export_and_import_fixtures():
    reqs = [
        Requirement("SYS-010", "The bus shall provide 28 V within 0.5 V.", verification_status="Passed", evidence="RPT-3"),
        Requirement("SYS-011", "The radio shall transmit at 4 kbps.", verification_status="Failed"),
    ]
    document = export_execution(reqs, project_key="DEMO", method_for=lambda r: "Test" if r.id == "SYS-010" else "Demonstration")
    assert document["tests"][0]["status"] == "PASSED"
    assert document["tests"][0]["testInfo"]["type"] == "Manual"
    assert document["tests"][0]["testInfo"]["requirementKeys"] == ["SYS-010"]
    assert document["tests"][1]["status"] == "FAILED"
    FIXTURES.mkdir(exist_ok=True)
    (FIXTURES / "xray_execution.json").write_text(json.dumps({
        "info": {"summary": "Fixture execution"},
        "tests": [
            {"status": "PASSED", "comment": "Bus test RPT-3", "testInfo": {"requirementKeys": ["SYS-010"], "summary": "SYS-010 Test"}},
            {"testKey": "SYS-011", "status": "FAIL", "comment": "Radio did not lock."},
        ],
    }, indent=2), encoding="utf-8")
    (FIXTURES / "xray_junit.xml").write_text(export_junit(reqs, method_for=lambda r: "Test"), encoding="utf-8")
    updates = import_results((FIXTURES / "xray_execution.json").read_text(encoding="utf-8"), "xray_execution.json")
    by_id = {u["req_id"]: u for u in updates}
    assert by_id["SYS-010"]["verification_status"] == "Passed"
    assert by_id["SYS-011"]["verification_status"] == "Failed"
    junit_updates = import_results((FIXTURES / "xray_junit.xml").read_text(encoding="utf-8"), "xray_junit.xml")
    junit_by = {u["req_id"]: u["verification_status"] for u in junit_updates}
    assert junit_by["SYS-010"] == "Passed"
    assert junit_by["SYS-011"] == "Failed"


def test_api_profile_closure_and_xray(monkeypatch):
    for key in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "JIRA_BASE_URL", "JIRA_API_TOKEN", "JIRA_PROJECT_KEY"):
        monkeypatch.delenv(key, raising=False)
    from fastapi.testclient import TestClient
    from verireq.app import app
    client = TestClient(app)
    cfg = client.get("/api/config").json()
    assert cfg["brand"]["product_name"] == "VeriReq"
    assert cfg["default_profile"] == "nasa"
    assert cfg["llm"]["enabled"] is False and cfg["jira"]["enabled"] is False
    labels = [m["label"] for m in cfg["brand"]["modules"]]
    assert labels == ["VeriReq Spec", "VeriReq Analyze", "VeriReq Trace", "VeriReq Verify", "VeriReq Insight"]
    page = client.get("/").text
    assert "VeriReq" in page and "Engineering Intelligence" in page
    assert "Intelligence behind every requirement." in page
    body = {"profile": "nasa", "requirements": [
        {"id": "SYS-PWR-010", "text": "The power subsystem shall provide 28 V within 0.5 V.",
         "verification_status": "Passed", "evidence": "RPT-1"},
        {"id": "SYS-PWR-020", "text": "The power subsystem shall provide power.", "parent_id": "MISSING"},
    ]}
    analysed = client.post("/api/analyze", json=body)
    assert analysed.status_code == 200
    result = analysed.json()
    assert result["profile"]["id"] == "nasa"
    assert result["summary"]["closure"]["closed"] == 1
    assert any(f["rule_id"] == "TRACE-01" for f in result["trace"]["findings"])
    exported = client.post("/api/xray/export", json=result)
    assert exported.status_code == 200
    parsed = import_results(exported.text, "export.json")
    assert any(item["req_id"] == "SYS-PWR-010" and item["verification_status"] == "Passed" for item in parsed)
    denied = client.post("/api/jira/push", json=result)
    assert denied.status_code == 400
    reqif = client.post("/api/reqif", json=result)
    assert reqif.status_code == 200 and b"REQ-IF" in reqif.content
    assert client.post("/api/analyze", data={"text": "nothing here"}).status_code == 422
