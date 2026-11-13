"""Parent/child and dependency links.

Links are data on each requirement (parent id, depends-on ids). They arrive
from the editor, from a table column, or from a ReqIF relation. This module
only reports broken and missing links; it does not invent a hierarchy.
"""
from __future__ import annotations

from typing import Dict, List

from .models import Finding, Requirement


def _f(req, rule_id, name, sev, msg, sug, match=""):
    return Finding(req_id=req.id, rule_id=rule_id, rule_name=name, severity=sev, message=msg,
                   suggestion=sug, match=match)


def link_graph(reqs: List[Requirement]) -> dict:
    ids = [r.id for r in reqs]
    known = set(ids)
    edges = []
    for r in reqs:
        if r.parent_id:
            edges.append({"from": r.parent_id, "to": r.id, "kind": "parent"})
        for dep in r.depends_on:
            edges.append({"from": r.id, "to": dep, "kind": "depends"})
    return {"nodes": [{"id": i} for i in ids], "edges": edges, "known": sorted(known)}


def trace_findings(reqs: List[Requirement]) -> List[Finding]:
    known = {r.id for r in reqs}
    children = {i: [] for i in known}
    depended = {i: [] for i in known}
    for r in reqs:
        if r.parent_id in known:
            children[r.parent_id].append(r.id)
        for dep in r.depends_on:
            if dep in known:
                depended[dep].append(r.id)
    any_link = any(r.parent_id or r.depends_on for r in reqs)
    out: List[Finding] = []
    for r in reqs:
        if r.parent_id and r.parent_id not in known:
            out.append(_f(
                r, "TRACE-01", "Broken parent link", "High",
                f"Parent '{r.parent_id}' is not in this set.",
                "Point the parent field at an existing requirement, or clear it if this is a root.",
                r.parent_id,
            ))
        missing = [d for d in r.depends_on if d not in known]
        if missing:
            out.append(_f(
                r, "TRACE-02", "Broken dependency", "High",
                f"Depends on {', '.join(missing)}, which is not in this set.",
                "Add the missing requirement or remove the dependency.",
                ", ".join(missing),
            ))
        linked = bool(r.parent_id) or bool(r.depends_on) or bool(children.get(r.id)) or bool(depended.get(r.id))
        if any_link and not linked:
            out.append(_f(
                r, "TRACE-03", "Orphan requirement", "Medium",
                "No parent, child, or dependency connects this statement to the rest of the set.",
                "Give it a parent, or record the requirement it depends on. Leave it unlinked only if it is intentionally standalone.",
                r.id,
            ))
    return out


def attach_by_requirement(findings: List[Finding]) -> Dict[str, List[Finding]]:
    by = {}
    for f in findings:
        by.setdefault(f.req_id, []).append(f)
    return by
