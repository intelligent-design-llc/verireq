"""Guards added after the demo-readiness review."""
import io
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from verireq.app import app
from verireq.export import to_xlsx
from verireq.extract import ExtractionError, extract
from verireq.jira_connector import JiraError, pull_statuses
from verireq.models import Requirement
from verireq.reqif import loads
from verireq.xray_connector import import_results


XXE = b"""<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<REQ-IF>&xxe;</REQ-IF>
"""

BILLION = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
]>
<REQ-IF>&lol3;</REQ-IF>
"""


def test_reqif_rejects_external_entities_and_expansion():
    with pytest.raises(ValueError):
        loads(XXE)
    with pytest.raises(ValueError):
        loads(BILLION)


def test_junit_import_rejects_entity_expansion():
    xml = b"""<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<testsuite><testcase name="&xxe;"/></testsuite>
"""
    with pytest.raises(ValueError):
        import_results(xml.decode(), "results.xml")


def test_office_zip_rejects_path_traversal_and_huge_expansion():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.xml", "nope")
    with pytest.raises(ExtractionError):
        extract("book.xlsx", buf.getvalue())
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("verireq.extract.MAX_ZIP_UNCOMPRESSED", 1000)
    huge = io.BytesIO()
    with zipfile.ZipFile(huge, "w") as zf:
        zf.writestr("word/document.xml", b"A" * 2000)
    try:
        with pytest.raises(ExtractionError):
            extract("note.docx", huge.getvalue())
    finally:
        monkeypatch.undo()


def test_filename_is_not_a_filesystem_path():
    csv_bytes = b"ID,Requirement\nSYS-010,The bus shall provide 5 V.\n"
    reqs = extract("../../etc/passwd.csv", csv_bytes)
    assert reqs[0].id == "SYS-010"


def test_csv_row_limit(monkeypatch):
    monkeypatch.setattr("verireq.extract.MAX_TABLE_ROWS", 2)
    payload = b"ID,Requirement\nA-10,The bus shall provide 5 V.\nB-10,The bus shall provide 3 V.\nC-10,The bus shall provide 1 V.\n"
    with pytest.raises(ExtractionError):
        extract("too.csv", payload)


def test_spreadsheet_formula_is_neutralised():
    result = {
        "profile": {"id": "nasa", "name": "NASA", "verification_methods": [{"name": "Test", "short": "T"}],
                    "references": [], "level_hint": "", "stage_hint": "", "verification_note": ""},
        "disclaimer": "draft",
        "summary": {"requirements": 1, "findings": 0, "requirements_with_findings": 0, "clean_requirements": 1,
                    "by_severity": {"High": 0, "Medium": 0, "Low": 0}, "by_rule": {}, "verification_methods": {},
                    "average_score": 100, "closure": {"closed": 0, "total": 1, "percent": 0, "by_state": {}}},
        "requirements": [{
            "id": "SYS-010", "text": "=HYPERLINK(\"http://example.invalid\")", "source": "", "score": 100,
            "findings": [], "verification": {"primary": "Test", "secondary": None, "rationale": ""},
            "verification_status": "Not started", "evidence": "", "closure": "Open", "parent_id": "",
            "depends_on": [], "method_override": "", "llm": None,
        }],
        "trace": {"findings": []},
        "tool": "VeriReq", "generated_at": "", "source": "t", "llm_used": False,
    }
    wb = load_workbook(io.BytesIO(to_xlsx(result)))
    texts = [c.value for row in wb["Requirements"].iter_rows() for c in row if isinstance(c.value, str)]
    assert any(v.startswith("'=HYPERLINK") for v in texts)


def test_upload_and_download_names(monkeypatch):
    from verireq.app import _download_name
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setattr("verireq.app.MAX_BYTES", 64)
    client = TestClient(app)
    big = client.post("/api/analyze", data={"text": "x" * 80})
    assert big.status_code == 413
    assert "\r" not in _download_name('report";\r\nX.xlsx')
    assert "\n" not in _download_name('report";\r\nX.xlsx')


def test_jira_rejects_credentialed_urls_and_odd_keys(monkeypatch):
    monkeypatch.setenv("JIRA_BASE_URL", "https://user:secret-token@example.invalid")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret-token")
    monkeypatch.setenv("JIRA_PROJECT_KEY", "DEMO")
    with pytest.raises(JiraError):
        pull_statuses(["DEMO-1"], client=object())
    monkeypatch.setenv("JIRA_BASE_URL", "file:///etc/passwd")
    with pytest.raises(JiraError):
        pull_statuses(["DEMO-1"], client=object())
    monkeypatch.setenv("JIRA_BASE_URL", "http://jira.example.com")
    with pytest.raises(JiraError, match="https"):
        pull_statuses(["DEMO-1"], client=object())
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.invalid")

    class Fake:
        def get(self, url, params=None):
            raise AssertionError(url)

    with pytest.raises(JiraError):
        pull_statuses(["../admin"], client=Fake())


def test_workbook_round_trip_still_opens():
    wb = Workbook()
    ws = wb.active
    ws.append(["ID", "Requirement"])
    ws.append(["SYS-010", "The bus shall provide 5 V."])
    buf = io.BytesIO()
    wb.save(buf)
    reqs = extract("plain.xlsx", buf.getvalue())
    assert reqs[0].text.startswith("The bus")
    assert httpx.get  # imported client stays available; this test makes no network call
