"""Optional Jira connector.

Off unless a base URL, an API token, and a project key are set. Jira Cloud
uses REST API v3 with email and token as Basic auth, and Atlassian document
format for the description. Jira Server and Data Center use REST API v2 with
a bearer personal access token and a plain-text description.

The token is read from the environment inside the process. It is not written
to disk, not written to logs, and not returned by the API. Redirects are not
followed, so the Authorization header cannot be sent to another host.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import List, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx

from .brand import PRODUCT_NAME
from .limits import MAX_JIRA_BATCH
from .models import Requirement, VERIFICATION_STATUSES

_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")
_PROJECT_RE = re.compile(r"^[A-Z][A-Z0-9]+$")

_DEFAULT_STATUS = {
    "not started": "Not started",
    "to do": "Not started",
    "open": "Not started",
    "planned": "Planned",
    "in progress": "In progress",
    "in review": "In progress",
    "passed": "Passed",
    "done": "Passed",
    "closed": "Passed",
    "failed": "Failed",
    "waived": "Waived",
}
_FALLBACK_TYPES = ("Requirement", "Story", "Task")


class JiraError(RuntimeError):
    pass


def config() -> dict:
    """Public view. Never includes the token."""
    base = os.environ.get("JIRA_BASE_URL", "").strip().rstrip("/")
    token = os.environ.get("JIRA_API_TOKEN", "").strip()
    email = os.environ.get("JIRA_EMAIL", "").strip()
    project = _project_from_env()
    issue_type = os.environ.get("JIRA_ISSUE_TYPE", "Requirement").strip() or "Requirement"
    try:
        deployment = _deployment(email)
    except JiraError:
        deployment = "auto"
    cloud_ready = deployment == "cloud" and bool(email)
    server_ready = deployment == "server"
    enabled = bool(base and token and project and (cloud_ready or server_ready))
    return {
        "enabled": enabled,
        "base_url": _public_base(base) if _safe_base(base) else "",
        "project": project,
        "issue_type": issue_type,
        "deployment": deployment if deployment in {"cloud", "server"} else "auto",
        "auth": "basic" if deployment == "cloud" else "bearer",
        "has_email": bool(email),
    }


def map_status(name: str, category: str = "", mapping: Optional[dict] = None) -> str:
    """Map a Jira status name or category onto a verification status."""
    table = mapping if mapping is not None else _status_table()
    folded = (name or "").strip().lower()
    if folded in table:
        return table[folded]
    if category == "done":
        return "Passed"
    if category == "indeterminate":
        return "In progress"
    if category == "new":
        return "Not started"
    return "Not started"


def test_connection(client: Optional[httpx.Client] = None) -> dict:
    """GET /myself and the configured project. Raises JiraError with a status-specific message."""
    raw = _raw()
    own = client is None
    client = client or _http_client(raw)
    try:
        me = _send(client, raw, "GET", f"/rest/api/{raw['version']}/myself")
        _raise_for_status(me, raw, "Test connection")
        body = me.json() if me.content else {}
        account = ""
        if isinstance(body, dict):
            account = str(body.get("displayName") or body.get("name") or "authenticated account")
        project = _send(client, raw, "GET", f"/rest/api/{raw['version']}/project/{raw['project']}")
        if project.status_code == 404:
            raise JiraError(f"Project {raw['project']} was not found (404). Check the project key.")
        _raise_for_status(project, raw, "Project lookup")
        names = _type_names(project.json() if project.content else {})
        return {
            "ok": True,
            "deployment": raw["deployment"],
            "project": raw["project"],
            "account": account,
            "issue_types": names,
        }
    finally:
        if own:
            client.close()


def push_requirements(reqs: List[Requirement], client: Optional[httpx.Client] = None) -> List[dict]:
    if len(reqs) > MAX_JIRA_BATCH:
        raise JiraError(f"Refusing to push more than {MAX_JIRA_BATCH} requirements at once.")
    raw = _raw()
    own = client is None
    client = client or _http_client(raw)
    try:
        available = _load_issue_types(client, raw)
        preferred = _choose_type(raw["issue_type"], available)
        results = []
        keys = {}
        for req in reqs:
            key, action = _upsert(client, raw, req, preferred, available)
            keys[req.id] = key
            results.append({"req_id": req.id, "key": key, "id": None, "action": action, "warnings": []})
        for req, row in zip(reqs, results):
            row["warnings"].extend(_link_related(client, raw, req, keys))
        return results
    finally:
        if own:
            client.close()


def pull_statuses(issue_keys: List[str], client: Optional[httpx.Client] = None) -> List[dict]:
    cleaned = []
    for key in issue_keys:
        key = (key or "").strip().upper()
        if not key:
            continue
        if not _KEY_RE.fullmatch(key):
            raise JiraError("An issue key is not in PROJECT-NUMBER form.")
        cleaned.append(key)
    if len(cleaned) > MAX_JIRA_BATCH:
        raise JiraError(f"Refusing to pull more than {MAX_JIRA_BATCH} issue keys at once.")
    if not cleaned:
        return []
    raw = _raw()
    own = client is None
    client = client or _http_client(raw)
    table = _status_table()
    try:
        found = _search_keys(client, raw, cleaned)
    finally:
        if own:
            client.close()
    out = []
    for key in cleaned:
        issue = found.get(key)
        if not issue:
            continue
        fields = issue.get("fields") or {}
        status = fields.get("status") or {}
        name = status.get("name") or ""
        category = ((status.get("statusCategory") or {}).get("key") or "").lower()
        out.append({
            "key": key,
            "status_name": name,
            "status_category": category,
            "verification_status": map_status(name, category, table),
            "summary": fields.get("summary") or "",
        })
    return out


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _project_from_env() -> str:
    return (os.environ.get("JIRA_PROJECT_KEY") or os.environ.get("JIRA_PROJECT") or "").strip()


def _deployment(email: str) -> str:
    mode = os.environ.get("JIRA_DEPLOYMENT", "auto").strip().lower() or "auto"
    if mode in {"cloud", "jira-cloud"}:
        return "cloud"
    if mode in {"server", "dc", "data-center", "datacenter"}:
        return "server"
    if mode != "auto":
        raise JiraError("JIRA_DEPLOYMENT must be cloud, server, or auto.")
    return "cloud" if email else "server"


def _safe_base(base: str) -> bool:
    if not base:
        return False
    parts = urlsplit(base)
    return parts.scheme == "https" and bool(parts.hostname) and not parts.username and not parts.password


def _public_base(base: str) -> str:
    if not base:
        return ""
    parts = urlsplit(base)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    path = (parts.path or "").rstrip("/")
    return urlunsplit(("https" if parts.scheme == "https" else parts.scheme, host, path, "", ""))


def _raw() -> dict:
    base = os.environ.get("JIRA_BASE_URL", "").strip().rstrip("/")
    token = os.environ.get("JIRA_API_TOKEN", "").strip()
    email = os.environ.get("JIRA_EMAIL", "").strip()
    project = _project_from_env()
    issue_type = os.environ.get("JIRA_ISSUE_TYPE", "Requirement").strip() or "Requirement"
    if not (base and token and project):
        raise JiraError("Jira connector is not configured. Set JIRA_BASE_URL, JIRA_API_TOKEN, and JIRA_PROJECT_KEY.")
    parts = urlsplit(base)
    if parts.username or parts.password:
        raise JiraError("JIRA_BASE_URL must not contain embedded credentials.")
    if parts.scheme != "https" or not parts.hostname:
        raise JiraError("JIRA_BASE_URL must be an https origin.")
    if not _PROJECT_RE.fullmatch(project):
        raise JiraError("JIRA_PROJECT_KEY is not a project key.")
    deployment = _deployment(email)
    if deployment == "cloud" and not email:
        raise JiraError("Jira Cloud needs JIRA_EMAIL as well as JIRA_API_TOKEN.")
    return {
        "base": _public_base(base),
        "token": token,
        "email": email,
        "project": project,
        "issue_type": issue_type[:40],
        "deployment": deployment,
        "version": "3" if deployment == "cloud" else "2",
        "parent_link": os.environ.get("JIRA_PARENT_LINK", "Relates").strip() or "Relates",
        "depends_link": os.environ.get("JIRA_DEPENDS_LINK", "Blocks").strip() or "Blocks",
    }


def _status_table() -> dict:
    table = dict(_DEFAULT_STATUS)
    raw = os.environ.get("JIRA_STATUS_MAP", "").strip()
    if not raw:
        return table
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JiraError("JIRA_STATUS_MAP is not valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise JiraError("JIRA_STATUS_MAP must be a JSON object.")
    allowed = set(VERIFICATION_STATUSES)
    for key, value in parsed.items():
        if value not in allowed:
            raise JiraError("JIRA_STATUS_MAP contains a status this tool does not use.")
        table[str(key).strip().lower()] = value
    return table


def _http_client(raw: dict) -> httpx.Client:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    kwargs = {"headers": headers, "timeout": httpx.Timeout(30.0, connect=10.0), "follow_redirects": False}
    if raw["deployment"] == "cloud":
        kwargs["auth"] = (raw["email"], raw["token"])
    else:
        headers["Authorization"] = f"Bearer {raw['token']}"
    return httpx.Client(**kwargs)


def _scrub(text: str, token: str) -> str:
    if token and text and token in text:
        return text.replace(token, "[redacted]")
    return text


def _send(client, raw: dict, method: str, path: str, json_body=None, params=None):
    url = raw["base"] + path
    for attempt in range(4):
        response = client.request(method, url, json=json_body, params=params)
        if response.status_code in {301, 302, 303, 307, 308}:
            raise JiraError("Jira returned a redirect, which is not followed.")
        if response.status_code != 429:
            return response
        if attempt == 3:
            raise JiraError("Jira rate limit persisted after retries (429).")
        wait = _retry_after(response)
        time.sleep(wait)
    return response


def _retry_after(response) -> float:
    raw = (response.headers.get("Retry-After") or "1").strip()
    try:
        wait = float(raw)
    except ValueError:
        wait = 1.0
    return min(max(wait, 0.0), 30.0)


def _error_text(response, token: str) -> str:
    try:
        data = response.json()
    except Exception:
        return ""
    parts = []
    if isinstance(data, dict):
        for item in data.get("errorMessages") or []:
            parts.append(str(item))
        errors = data.get("errors") or {}
        if isinstance(errors, dict):
            parts.extend(f"{key}: {value}" for key, value in errors.items())
    return _scrub(" ".join(parts)[:400], token)


def _raise_for_status(response, raw: dict, context: str) -> None:
    code = response.status_code
    if code < 400:
        return
    if code == 401:
        raise JiraError(f"{context}: Jira rejected the credentials (401).")
    if code == 403:
        raise JiraError(f"{context}: Jira refused access (403). The account is authenticated but not allowed to do this.")
    if code == 404:
        raise JiraError(f"{context}: Jira could not find that resource (404). Check the site URL and project key.")
    detail = _error_text(response, raw["token"])
    if detail:
        raise JiraError(f"{context}: Jira returned {code}. {detail}")
    raise JiraError(f"{context}: Jira returned {code}.")


# ---------------------------------------------------------------------------
# Issues
# ---------------------------------------------------------------------------


def _label(req_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "-", req_id).strip("-") or "requirement"
    return f"verireq-{safe}"[:255]


def _summary(req: Requirement) -> str:
    text = f"{req.id}: {req.text}".replace("\n", " ")
    return text if len(text) <= 250 else text[:247] + "..."


def _plain_description(req: Requirement) -> str:
    method = req.method_override or ""
    return (
        f"Requirement {req.id}\n\n{req.text}\n\n"
        f"Verification status: {req.verification_status or 'Not started'}\n"
        f"Method: {method or '(draft in ' + PRODUCT_NAME + ')'}\n"
        f"Evidence: {req.evidence or '(none)'}"
    )[:32000]


def _description(raw: dict, req: Requirement):
    text = _plain_description(req)
    if raw["deployment"] == "cloud":
        return {"type": "doc", "version": 1, "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}
        ]}
    return text


def _fields(raw: dict, req: Requirement, issue_type: str) -> dict:
    return {
        "project": {"key": raw["project"]},
        "summary": _summary(req),
        "issuetype": {"name": issue_type},
        "labels": ["verireq", _label(req.id)],
        "description": _description(raw, req),
    }


def _load_issue_types(client, raw: dict) -> List[str]:
    response = _send(client, raw, "GET", f"/rest/api/{raw['version']}/project/{raw['project']}")
    if response.status_code == 404:
        raise JiraError(f"Project {raw['project']} was not found (404). Check the project key.")
    _raise_for_status(response, raw, "Project lookup")
    return _type_names(response.json() if response.content else {})


def _type_names(payload) -> List[str]:
    types = payload.get("issueTypes") if isinstance(payload, dict) else None
    names = []
    for item in types or []:
        if isinstance(item, dict) and item.get("name") and not item.get("subtask"):
            names.append(str(item["name"]))
    return names


def _choose_type(preferred: str, available: List[str]) -> str:
    if not available:
        return preferred
    order = [preferred, *_FALLBACK_TYPES]
    for name in order:
        if name in available:
            return name
    return available[0]


def _candidate_types(preferred: str, available: List[str]) -> List[str]:
    ordered = []
    for name in (preferred, *_FALLBACK_TYPES):
        if name and name not in ordered and (not available or name in available):
            ordered.append(name)
    if not ordered:
        ordered.append(preferred or "Task")
    return ordered


def _upsert(client, raw, req: Requirement, preferred: str, available: List[str]):
    existing = str((req.external or {}).get("jira") or "").strip().upper()
    if existing and _KEY_RE.fullmatch(existing):
        _update(client, raw, existing, req)
        return existing, "updated"
    found = _search_one(client, raw, f'project = {raw["project"]} AND labels = "{_label(req.id)}"')
    if found:
        _update(client, raw, found, req)
        return found, "updated"
    return _create(client, raw, req, _candidate_types(preferred, available)), "created"


def _update(client, raw, key: str, req: Requirement) -> None:
    body = {"fields": {"summary": _summary(req), "labels": ["verireq", _label(req.id)], "description": _description(raw, req)}}
    response = _send(client, raw, "PUT", f"/rest/api/{raw['version']}/issue/{key}", json_body=body)
    _raise_for_status(response, raw, f"Update {req.id}")


def _create(client, raw, req: Requirement, types: List[str]) -> str:
    last = None
    for index, issue_type in enumerate(types):
        response = _send(
            client, raw, "POST", f"/rest/api/{raw['version']}/issue",
            json_body={"fields": _fields(raw, req, issue_type)},
        )
        if response.status_code < 400:
            payload = response.json() if response.content else {}
            key = str(payload.get("key") or "")
            if not _KEY_RE.fullmatch(key):
                raise JiraError(f"Create {req.id}: Jira did not return an issue key.")
            return key
        detail = _error_text(response, raw["token"]).lower()
        last = response
        if response.status_code == 400 and "issuetype" in detail and index < len(types) - 1:
            continue
        _raise_for_status(response, raw, f"Create {req.id}")
    _raise_for_status(last, raw, f"Create {req.id}")
    raise JiraError(f"Create {req.id}: Jira did not create an issue.")


def _search_one(client, raw, jql: str) -> str:
    issues = _search_page(client, raw, jql, max_results=1)
    if not issues:
        return ""
    key = str(issues[0].get("key") or "")
    return key if _KEY_RE.fullmatch(key) else ""


def _search_keys(client, raw, keys: List[str]) -> dict:
    found = {}
    chunk = 50
    for start in range(0, len(keys), chunk):
        group = keys[start:start + chunk]
        jql = "key in (" + ", ".join(group) + ")"
        for issue in _search_all(client, raw, jql):
            key = str(issue.get("key") or "")
            if key:
                found[key] = issue
    return found


def _search_all(client, raw, jql: str) -> List[dict]:
    issues = []
    if raw["deployment"] == "cloud":
        token = None
        for _ in range(20):
            body = {"jql": jql, "maxResults": 50, "fields": ["summary", "status"]}
            if token:
                body["nextPageToken"] = token
            response = _send(client, raw, "POST", "/rest/api/3/search/jql", json_body=body)
            _raise_for_status(response, raw, "Search")
            payload = response.json() if response.content else {}
            issues.extend(payload.get("issues") or [])
            token = payload.get("nextPageToken")
            if payload.get("isLast", not token) or not token:
                break
        return issues
    start_at = 0
    for _ in range(20):
        response = _send(client, raw, "POST", "/rest/api/2/search", json_body={
            "jql": jql, "startAt": start_at, "maxResults": 50, "fields": ["summary", "status"],
        })
        _raise_for_status(response, raw, "Search")
        payload = response.json() if response.content else {}
        page = payload.get("issues") or []
        issues.extend(page)
        start_at += len(page)
        total = int(payload.get("total") or 0)
        if not page or start_at >= total:
            break
    return issues


def _search_page(client, raw, jql: str, max_results: int) -> List[dict]:
    if raw["deployment"] == "cloud":
        response = _send(client, raw, "POST", "/rest/api/3/search/jql", json_body={
            "jql": jql, "maxResults": max_results, "fields": ["summary", "status"],
        })
    else:
        response = _send(client, raw, "POST", "/rest/api/2/search", json_body={
            "jql": jql, "startAt": 0, "maxResults": max_results, "fields": ["summary", "status"],
        })
    _raise_for_status(response, raw, "Search")
    payload = response.json() if response.content else {}
    return list(payload.get("issues") or [])


def _link_related(client, raw, req: Requirement, keys: dict) -> List[str]:
    warnings = []
    source = keys.get(req.id)
    if not source:
        return warnings
    parent_key = keys.get(req.parent_id) or (_search_one(client, raw, f'project = {raw["project"]} AND labels = "{_label(req.parent_id)}"') if req.parent_id else "")
    if req.parent_id and parent_key:
        warnings.extend(_ensure_link(client, raw, raw["parent_link"], source, parent_key, req.id))
    elif req.parent_id:
        warnings.append(f"No Jira issue for parent {req.parent_id}.")
    for dep in req.depends_on or []:
        dep_key = keys.get(dep) or _search_one(client, raw, f'project = {raw["project"]} AND labels = "{_label(dep)}"')
        if not dep_key:
            warnings.append(f"No Jira issue for dependency {dep}.")
            continue
        warnings.extend(_ensure_link(client, raw, raw["depends_link"], source, dep_key, req.id))
    return warnings


def _ensure_link(client, raw, link_type: str, inward: str, outward: str, req_id: str) -> List[str]:
    if inward == outward:
        return []
    existing = _send(client, raw, "GET", f"/rest/api/{raw['version']}/issue/{inward}", params={"fields": "issuelinks"})
    if existing.status_code < 400:
        for link in ((existing.json() or {}).get("fields") or {}).get("issuelinks") or []:
            kind = ((link.get("type") or {}).get("name") or "")
            other = (link.get("outwardIssue") or link.get("inwardIssue") or {}).get("key")
            if kind == link_type and other in {inward, outward}:
                return []
    response = _send(client, raw, "POST", f"/rest/api/{raw['version']}/issueLink", json_body={
        "type": {"name": link_type},
        "inwardIssue": {"key": inward},
        "outwardIssue": {"key": outward},
    })
    if response.status_code < 400:
        return []
    detail = _error_text(response, raw["token"]).lower()
    if "already" in detail:
        return []
    if response.status_code in {400, 404}:
        return [f"Link type {link_type} could not be created for {req_id} ({response.status_code})."]
    _raise_for_status(response, raw, f"Link {req_id}")
    return []
