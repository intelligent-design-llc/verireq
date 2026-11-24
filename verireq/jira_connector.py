"""Optional Jira connector.

Off unless JIRA_BASE_URL, JIRA_API_TOKEN, and JIRA_PROJECT_KEY are set.
The token is read from the environment inside the process and is never
written to disk, logs, or API responses. Issue text is sent only when a
caller explicitly pushes.

Jira Cloud REST API v3 is used: create issue, then read status back.
"""
from __future__ import annotations

import os
import re
from typing import List, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx

from .brand import PRODUCT_NAME
from .limits import MAX_JIRA_BATCH
from .models import Requirement

_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")


class JiraError(RuntimeError):
    pass


def config() -> dict:
    base = os.environ.get("JIRA_BASE_URL", "").strip().rstrip("/")
    token = os.environ.get("JIRA_API_TOKEN", "").strip()
    email = os.environ.get("JIRA_EMAIL", "").strip()
    project = os.environ.get("JIRA_PROJECT_KEY", "").strip()
    issue_type = os.environ.get("JIRA_ISSUE_TYPE", "Task").strip() or "Task"
    return {
        "enabled": bool(base and token and project),
        "base_url": _public_base(base),
        "project": project,
        "issue_type": issue_type,
        "auth": "basic" if email else "bearer",
        "has_email": bool(email),
    }


def _public_base(base: str) -> str:
    if not base:
        return ""
    parts = urlsplit(base)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, "", "", ""))


def _client_kwargs(cfg_raw: dict) -> dict:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    kwargs = {"headers": headers, "timeout": 30}
    if cfg_raw["email"]:
        kwargs["auth"] = (cfg_raw["email"], cfg_raw["token"])
    else:
        headers["Authorization"] = f"Bearer {cfg_raw['token']}"
    return kwargs


def _raw() -> dict:
    base = os.environ.get("JIRA_BASE_URL", "").strip().rstrip("/")
    token = os.environ.get("JIRA_API_TOKEN", "").strip()
    email = os.environ.get("JIRA_EMAIL", "").strip()
    project = os.environ.get("JIRA_PROJECT_KEY", "").strip()
    issue_type = os.environ.get("JIRA_ISSUE_TYPE", "Task").strip() or "Task"
    if not (base and token and project):
        raise JiraError("Jira connector is not configured. Set JIRA_BASE_URL, JIRA_API_TOKEN, and JIRA_PROJECT_KEY.")
    parts = urlsplit(base)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise JiraError("JIRA_BASE_URL must be an http(s) origin without embedded credentials.")
    if not re.fullmatch(r"[A-Z][A-Z0-9]+", project):
        raise JiraError("JIRA_PROJECT_KEY is not a project key.")
    origin = _public_base(base)
    return {"base": origin, "token": token, "email": email, "project": project, "issue_type": issue_type[:40]}


def _label(req_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "-", req_id).strip("-") or "requirement"
    return f"verireq-{safe}"[:255]


def _adf(text: str) -> dict:
    return {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": text[:32000]}]}
    ]}


def push_requirements(reqs: List[Requirement], client: Optional[httpx.Client] = None) -> List[dict]:
    if len(reqs) > MAX_JIRA_BATCH:
        raise JiraError(f"Refusing to push more than {MAX_JIRA_BATCH} requirements at once.")
    raw = _raw()
    own = client is None
    client = client or httpx.Client(**_client_kwargs(raw))
    created = []
    try:
        for req in reqs:
            summary = f"{req.id}: {req.text}".replace("\n", " ")
            if len(summary) > 250:
                summary = summary[:247] + "..."
            method = req.method_override or ""
            body = {
                "fields": {
                    "project": {"key": raw["project"]},
                    "summary": summary,
                    "issuetype": {"name": raw["issue_type"]},
                    "labels": ["verireq", _label(req.id)],
                    "description": _adf(
                        f"Requirement {req.id}\n\n{req.text}\n\n"
                        f"Verification status: {req.verification_status or 'Not started'}\n"
                        f"Method override: {method or '(draft in ' + PRODUCT_NAME + ')'}\n"
                        f"Evidence: {req.evidence or '(none)'}"
                    ),
                }
            }
            response = client.post(f"{raw['base']}/rest/api/3/issue", json=body)
            if response.status_code >= 400:
                raise JiraError(f"Jira rejected {req.id} ({response.status_code}).")
            payload = response.json()
            created.append({"req_id": req.id, "key": payload.get("key"), "id": payload.get("id")})
    finally:
        if own:
            client.close()
    return created


def pull_statuses(issue_keys: List[str], client: Optional[httpx.Client] = None) -> List[dict]:
    raw = _raw()
    own = client is None
    client = client or httpx.Client(**_client_kwargs(raw))
    out = []
    try:
        if len(issue_keys) > MAX_JIRA_BATCH:
            raise JiraError(f"Refusing to pull more than {MAX_JIRA_BATCH} issue keys at once.")
        for key in issue_keys:
            key = (key or "").strip().upper()
            if not key:
                continue
            if not _KEY_RE.fullmatch(key):
                raise JiraError("An issue key is not in PROJECT-NUMBER form.")
            response = client.get(f"{raw['base']}/rest/api/3/issue/{key}", params={"fields": "status,summary"})
            if response.status_code >= 400:
                raise JiraError(f"Jira could not read {key} ({response.status_code}).")
            fields = (response.json() or {}).get("fields") or {}
            status = fields.get("status") or {}
            name = status.get("name") or ""
            category = ((status.get("statusCategory") or {}).get("key") or "").lower()
            out.append({
                "key": key,
                "status_name": name,
                "status_category": category,
                "verification_status": map_status(name, category),
                "summary": fields.get("summary") or "",
            })
    finally:
        if own:
            client.close()
    return out


def map_status(name: str, category: str = "") -> str:
    """Map a Jira status name or category onto a verification status."""
    folded = (name or "").strip().lower()
    known = {
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
    if folded in known:
        return known[folded]
    if category == "done":
        return "Passed"
    if category == "indeterminate":
        return "In progress"
    if category == "new":
        return "Not started"
    return "Not started"
