"""Contract tests against recorded Jira Cloud and Data Center response shapes.

Shapes follow Atlassian's published REST examples: Cloud search/jql uses
nextPageToken, Data Center search uses startAt/total, create returns id and
key, and errors use errorMessages/errors. No live site is contacted.
"""
import json

import httpx
import pytest

from verireq.jira_connector import JiraError, pull_statuses, push_requirements
from verireq.jira_connector import test_connection as jira_test_connection
from verireq.models import Requirement


def _response(method, url, status, payload, headers=None):
    return httpx.Response(status, json=payload, headers=headers or {}, request=httpx.Request(method, url))


class Router:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def request(self, method, url, json=None, params=None):
        self.calls.append({"method": method, "url": url, "json": json, "params": params})
        if not self.script:
            raise AssertionError(f"unexpected {method} {url}")
        expected, status, payload, headers = self.script.pop(0)
        assert method == expected[0], (method, expected, url)
        assert expected[1] in url, (url, expected)
        return _response(method, url, status, payload, headers)

    def close(self):
        pass


def _env(monkeypatch, deployment):
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret-token")
    monkeypatch.setenv("JIRA_PROJECT_KEY", "DEMO")
    monkeypatch.setenv("JIRA_DEPLOYMENT", deployment)
    if deployment == "cloud":
        monkeypatch.setenv("JIRA_EMAIL", "qa@example.com")
    else:
        monkeypatch.delenv("JIRA_EMAIL", raising=False)


def _project(types):
    return {"key": "DEMO", "issueTypes": [{"name": name, "subtask": False} for name in types]}


def _issue(key, status="To Do", category="new"):
    return {"key": key, "id": "10001", "fields": {
        "summary": "text",
        "status": {"name": status, "statusCategory": {"key": category}},
        "issuelinks": [],
    }}


def test_cloud_create_uses_adf_and_basic_shape(monkeypatch):
    _env(monkeypatch, "cloud")
    router = Router([
        (("GET", "/rest/api/3/project/DEMO"), 200, _project(["Requirement", "Task"]), None),
        (("POST", "/rest/api/3/search/jql"), 200, {"issues": [], "isLast": True}, None),
        (("POST", "/rest/api/3/issue"), 201, {"id": "10012", "key": "DEMO-12", "self": "https://example.atlassian.net/rest/api/3/issue/10012"}, None),
    ])
    created = push_requirements([Requirement("SYS-010", "The bus shall provide 28 V.")], client=router)
    assert created[0]["key"] == "DEMO-12" and created[0]["action"] == "created"
    body = router.calls[2]["json"]
    assert body["fields"]["description"]["type"] == "doc"
    assert body["fields"]["issuetype"]["name"] == "Requirement"
    assert "secret-token" not in json.dumps(body)


def test_cloud_updates_when_the_label_search_finds_an_issue(monkeypatch):
    _env(monkeypatch, "cloud")
    router = Router([
        (("GET", "/rest/api/3/project/DEMO"), 200, _project(["Task"]), None),
        (("POST", "/rest/api/3/search/jql"), 200, {"issues": [_issue("DEMO-4")], "isLast": True}, None),
        (("PUT", "/rest/api/3/issue/DEMO-4"), 204, {}, None),
    ])
    created = push_requirements([Requirement("SYS-010", "The bus shall provide 28 V.")], client=router)
    assert created[0]["action"] == "updated" and created[0]["key"] == "DEMO-4"
    assert not any(call["url"].endswith("/issue") and call["method"] == "POST" for call in router.calls)


def test_cloud_links_parent_and_dependency(monkeypatch):
    _env(monkeypatch, "cloud")
    router = Router([
        (("GET", "/rest/api/3/project/DEMO"), 200, _project(["Task"]), None),
        (("POST", "/rest/api/3/search/jql"), 200, {"issues": [], "isLast": True}, None),
        (("POST", "/rest/api/3/issue"), 201, {"id": "1", "key": "DEMO-1"}, None),
        (("POST", "/rest/api/3/search/jql"), 200, {"issues": [], "isLast": True}, None),
        (("POST", "/rest/api/3/issue"), 201, {"id": "2", "key": "DEMO-2"}, None),
        (("GET", "/rest/api/3/issue/DEMO-2"), 200, _issue("DEMO-2"), None),
        (("POST", "/rest/api/3/issueLink"), 201, {}, None),
        (("GET", "/rest/api/3/issue/DEMO-2"), 200, _issue("DEMO-2"), None),
        (("POST", "/rest/api/3/issueLink"), 201, {}, None),
    ])
    reqs = [
        Requirement("SYS-010", "The bus shall provide 28 V."),
        Requirement("SYS-011", "The radio shall transmit.", parent_id="SYS-010", depends_on=["SYS-010"]),
    ]
    created = push_requirements(reqs, client=router)
    assert [row["key"] for row in created] == ["DEMO-1", "DEMO-2"]
    link_types = [call["json"]["type"]["name"] for call in router.calls if call["url"].endswith("/issueLink")]
    assert link_types == ["Relates", "Blocks"]


def test_cloud_search_paginates_with_next_page_token(monkeypatch):
    _env(monkeypatch, "cloud")
    router = Router([
        (("POST", "/rest/api/3/search/jql"), 200, {
            "issues": [_issue("DEMO-1", "Done", "done")],
            "nextPageToken": "page-2",
            "isLast": False,
        }, None),
        (("POST", "/rest/api/3/search/jql"), 200, {
            "issues": [_issue("DEMO-2", "In Progress", "indeterminate")],
            "isLast": True,
        }, None),
    ])
    pulled = pull_statuses(["DEMO-1", "DEMO-2"], client=router)
    assert [row["verification_status"] for row in pulled] == ["Passed", "In progress"]
    assert router.calls[1]["json"]["nextPageToken"] == "page-2"


def test_server_create_uses_plain_description(monkeypatch):
    _env(monkeypatch, "server")
    router = Router([
        (("GET", "/rest/api/2/project/DEMO"), 200, _project(["Task"]), None),
        (("POST", "/rest/api/2/search"), 200, {"startAt": 0, "maxResults": 1, "total": 0, "issues": []}, None),
        (("POST", "/rest/api/2/issue"), 201, {"id": "100", "key": "DEMO-9"}, None),
    ])
    created = push_requirements([Requirement("SYS-010", "The bus shall provide 28 V.")], client=router)
    assert created[0]["key"] == "DEMO-9"
    assert isinstance(router.calls[2]["json"]["fields"]["description"], str)


def test_server_search_paginates_with_start_at(monkeypatch):
    _env(monkeypatch, "server")
    router = Router([
        (("POST", "/rest/api/2/search"), 200, {
            "startAt": 0, "maxResults": 1, "total": 2,
            "issues": [_issue("DEMO-1", "To Do", "new")],
        }, None),
        (("POST", "/rest/api/2/search"), 200, {
            "startAt": 1, "maxResults": 1, "total": 2,
            "issues": [_issue("DEMO-2", "Done", "done")],
        }, None),
    ])
    pulled = pull_statuses(["DEMO-1", "DEMO-2"], client=router)
    assert [row["key"] for row in pulled] == ["DEMO-1", "DEMO-2"]
    assert router.calls[1]["json"]["startAt"] == 1


def test_requirement_issue_type_falls_back_to_task(monkeypatch):
    _env(monkeypatch, "cloud")
    monkeypatch.setenv("JIRA_ISSUE_TYPE", "Requirement")
    router = Router([
        (("GET", "/rest/api/3/project/DEMO"), 200, _project(["Requirement", "Task"]), None),
        (("POST", "/rest/api/3/search/jql"), 200, {"issues": [], "isLast": True}, None),
        (("POST", "/rest/api/3/issue"), 400, {"errors": {"issuetype": "Specify a valid issue type"}}, None),
        (("POST", "/rest/api/3/issue"), 201, {"id": "7", "key": "DEMO-7"}, None),
    ])
    created = push_requirements([Requirement("SYS-010", "The bus shall provide 28 V.")], client=router)
    assert created[0]["key"] == "DEMO-7"
    assert [call["json"]["fields"]["issuetype"]["name"] for call in router.calls if call["method"] == "POST" and call["url"].endswith("/issue")] == ["Requirement", "Task"]


def test_connection_reports_401_and_retries_429(monkeypatch):
    _env(monkeypatch, "cloud")
    denied = Router([
        (("GET", "/rest/api/3/myself"), 401, {"message": "Client must be authenticated to access this resource."}, None),
    ])
    with pytest.raises(JiraError, match="401"):
        jira_test_connection(client=denied)

    monkeypatch.setenv("JIRA_PROJECT_KEY", "MISSING")
    missing = Router([
        (("GET", "/rest/api/3/myself"), 200, {"displayName": "QA", "accountId": "abc"}, None),
        (("GET", "/rest/api/3/project/MISSING"), 404, {"errorMessages": ["No project could be found with key 'MISSING'."], "errors": {}}, None),
    ])
    with pytest.raises(JiraError, match="404"):
        jira_test_connection(client=missing)

    monkeypatch.setenv("JIRA_PROJECT_KEY", "DEMO")
    limited = Router([
        (("GET", "/rest/api/3/project/DEMO"), 200, _project(["Task"]), None),
        (("POST", "/rest/api/3/search/jql"), 429, {"errorMessages": ["Rate limited"]}, {"Retry-After": "0"}),
        (("POST", "/rest/api/3/search/jql"), 200, {"issues": [], "isLast": True}, None),
        (("POST", "/rest/api/3/issue"), 201, {"id": "8", "key": "DEMO-8"}, None),
    ])
    created = push_requirements([Requirement("SYS-010", "The bus shall provide 28 V.")], client=limited)
    assert created[0]["key"] == "DEMO-8"
    assert sum(1 for call in limited.calls if "search/jql" in call["url"]) == 2


def test_connection_reports_403(monkeypatch):
    _env(monkeypatch, "server")
    router = Router([
        (("GET", "/rest/api/2/myself"), 403, {"errorMessages": ["You do not have permission."], "errors": {}}, None),
    ])
    with pytest.raises(JiraError, match="403"):
        jira_test_connection(client=router)
