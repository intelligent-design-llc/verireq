"""Xray file interchange. No Xray account and no network call.

Export writes the JSON execution document Xray documents for importing
results, including testInfo so a Manual test can be created and linked to
the requirement id. Cloud status names (PASSED, FAILED, EXECUTING, TODO)
are written on export.

Import reads that JSON back, and also JUnit XML with the property names
Xray's JUnit extension documents (test_key, requirements, test_summary).
Server/DC short names (PASS, FAIL) are accepted on import as well.
"""
from __future__ import annotations

import json
import re
from typing import List
from xml.sax.saxutils import escape

from .brand import PRODUCT_NAME
from .safe_xml import parse_xml
from .models import Requirement

_STATUS_TO_XRAY = {
    "Not started": "TODO",
    "Planned": "TODO",
    "In progress": "EXECUTING",
    "Passed": "PASSED",
    "Failed": "FAILED",
    "Waived": "ABORTED",
}
_XRAY_TO_STATUS = {
    "TODO": "Not started",
    "EXECUTING": "In progress",
    "PASSED": "Passed",
    "PASS": "Passed",
    "FAILED": "Failed",
    "FAIL": "Failed",
    "ABORTED": "Waived",
    "BLOCKED": "In progress",
    "SKIPPED": "Not started",
}


def export_execution(reqs: List[Requirement], project_key: str = "", method_for=None) -> dict:
    """Return an Xray JSON execution document. ``method_for(req)`` supplies the drafted method."""
    tests = []
    for req in reqs:
        method = ""
        if method_for is not None:
            method = method_for(req) or ""
        method = req.method_override or method or "Test"
        status = _STATUS_TO_XRAY.get(req.verification_status or "Not started", "TODO")
        summary = f"{req.id} {method}"
        if len(summary) > 250:
            summary = summary[:250]
        tests.append({
            "status": status,
            "comment": req.evidence or f"Evidence not yet recorded for {req.id}.",
            "testInfo": {
                "projectKey": project_key,
                "summary": summary,
                "type": "Manual",
                "testType": "Manual",
                "requirementKeys": [req.id],
                "labels": ["verireq", _label(method)],
                "steps": [{
                    "action": f"Perform {method} for requirement {req.id}.",
                    "data": req.text,
                    "result": "Record the evidence reference and the pass or fail result.",
                }],
            },
        })
    return {
        "info": {
            "summary": f"{PRODUCT_NAME} verification set",
            "description": (
                f"Verification items exported from {PRODUCT_NAME}. "
                "Each testInfo.requirementKeys entry is the requirement id in this tool, "
                "not a Jira issue key, until you link them in Jira."
            ),
        },
        "tests": tests,
    }


def export_junit(reqs: List[Requirement], method_for=None) -> str:
    cases = []
    for req in reqs:
        method = req.method_override or (method_for(req) if method_for else "") or "Test"
        name = escape(f"{req.id} {method}")
        props = (
            f'<property name="test_key" value="{escape(req.id)}"/>'
            f'<property name="requirements" value="{escape(req.id)}"/>'
            f'<property name="test_summary" value="{escape(name)}"/>'
        )
        body = ""
        if (req.verification_status or "") == "Failed":
            body = "<failure message=\"Verification status is Failed\"/>"
        elif (req.verification_status or "") in {"Not started", "Planned"}:
            body = "<skipped/>"
        cases.append(
            f'<testcase classname="verireq.verification" name="{name}">'
            f"<properties>{props}</properties>{body}</testcase>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<testsuite name="{escape(PRODUCT_NAME)}" tests="{len(reqs)}">'
        + "".join(cases) + "</testsuite>"
    )


def import_results(payload: str, filename: str = "") -> List[dict]:
    """Return ``{req_id, verification_status, evidence}`` updates. Unknown shape raises ValueError."""
    text = payload.lstrip()
    name = (filename or "").lower()
    if name.endswith(".xml") or text.startswith("<"):
        return _from_junit(text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Xray import needs a JSON execution document or JUnit XML.") from exc
    tests = data.get("tests") if isinstance(data, dict) else data
    if not isinstance(tests, list):
        raise ValueError("Xray JSON needs a tests array.")
    updates = []
    for test in tests:
        if not isinstance(test, dict):
            continue
        info = test.get("testInfo") or {}
        keys = list(info.get("requirementKeys") or [])
        if test.get("testKey"):
            keys.append(str(test["testKey"]))
        status = _XRAY_TO_STATUS.get(str(test.get("status") or "").upper())
        if not status:
            continue
        evidence = test.get("comment") or ""
        evidences = test.get("evidence") or test.get("evidences") or []
        if isinstance(evidences, list) and evidences:
            names = []
            for item in evidences:
                if isinstance(item, dict):
                    names.append(str(item.get("filename") or item.get("name") or ""))
            extra = ", ".join(n for n in names if n)
            if extra:
                evidence = (evidence + " " if evidence else "") + f"Evidence files: {extra}"
        for key in keys:
            key = str(key).strip()
            if key:
                updates.append({"req_id": key, "verification_status": status, "evidence": evidence.strip()})
    return updates


def _from_junit(text: str) -> List[dict]:
    root = parse_xml(text.encode("utf-8"))
    updates = []
    for case in root.iter("testcase"):
        props = {}
        for prop in case.findall("properties/property"):
            props[(prop.get("name") or "").lower()] = prop.get("value") or ""
        req_ids = []
        for bucket in (props.get("requirements"), props.get("requirement"), props.get("test_key")):
            if bucket:
                req_ids.extend(p.strip() for p in re.split(r"[,;\s]+", bucket) if p.strip())
        if not req_ids and case.get("name"):
            token = case.get("name").split()[0]
            if token:
                req_ids.append(token)
        if case.find("failure") is not None or case.find("error") is not None:
            status = "Failed"
        elif case.find("skipped") is not None:
            status = "Not started"
        else:
            status = "Passed"
        evidence = props.get("testrun_comment") or case.get("name") or ""
        for req_id in req_ids:
            updates.append({"req_id": req_id, "verification_status": status, "evidence": evidence})
    return updates


def _label(method: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", method).strip("-").lower() or "method"
