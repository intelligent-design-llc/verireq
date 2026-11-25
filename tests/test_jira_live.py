"""Opt-in round trip against a real Jira project.

Skipped unless JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, and JIRA_PROJECT
(or JIRA_PROJECT_KEY) are set. See docs/jira-setup.md.
"""
import uuid

import pytest

from verireq.jira_connector import JiraError, _http_client, _raw, _send, pull_statuses, push_requirements
from verireq.models import Requirement

pytestmark = pytest.mark.jira_live


def _configured():
    import os
    return all(os.environ.get(name, "").strip() for name in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN")) and (
        os.environ.get("JIRA_PROJECT", "").strip() or os.environ.get("JIRA_PROJECT_KEY", "").strip()
    )


@pytest.fixture(autouse=True)
def _skip_without_jira():
    if not _configured():
        pytest.skip("Set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, and JIRA_PROJECT to run the live Jira test.")


def test_live_push_pull_and_delete():
    req_id = "LIVE-" + uuid.uuid4().hex[:8].upper()
    created = push_requirements([Requirement(req_id, "The live check shall create and delete one issue.")])
    key = created[0]["key"]
    assert key
    try:
        pulled = pull_statuses([key])
        assert pulled and pulled[0]["key"] == key
        assert pulled[0]["verification_status"]
    finally:
        raw = _raw()
        client = _http_client(raw)
        try:
            response = _send(client, raw, "DELETE", f"/rest/api/{raw['version']}/issue/{key}")
            if response.status_code not in {204, 200, 404}:
                raise JiraError(f"Cleanup of {key} returned {response.status_code}.")
        finally:
            client.close()
