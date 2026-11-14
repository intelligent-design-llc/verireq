"""Analysis pipeline: requirements -> findings -> verification draft -> closure -> result dict."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import List, Optional

from . import __version__
from .brand import PRODUCT_NAME, public_brand
from .closure import closure_state, summarize
from .consistency import consistency_findings
from .insight import build_insight
from .models import Requirement, SEVERITY_ORDER
from .profiles import resolve_profile
from .rules import check_all, quality_score
from .trace import attach_by_requirement, link_graph, trace_findings
from .verification import draft_all

DISCLAIMER = (
    "ADVISORY ONLY. Automatically generated draft for engineering review; it does not replace "
    "engineering judgement, product-assurance review, or customer approval. Human sign-off is required. "
    "The profile named in this report selects terminology, verification methods, and checks. "
    "It does not reproduce standard text and it is not an approval by any agency or tool vendor. "
    "With the LLM pass disabled and the Jira connector left unconfigured, requirement text stays in this process. "
    "Do not enable the LLM pass or the Jira connector for ITAR/EAR-controlled or classified data "
    "unless that endpoint is authorised to receive it."
)


def analyse(reqs: List[Requirement], source_name: str = "pasted text", profile=None) -> dict:
    profile = resolve_profile(profile)
    findings = check_all(reqs, profile)
    findings.extend(consistency_findings(reqs))
    traces = trace_findings(reqs)
    verifs = {v.req_id: v for v in draft_all(reqs, profile)}
    by_req = {}
    for f in findings:
        by_req.setdefault(f.req_id, []).append(f)
    trace_by = attach_by_requirement(traces)
    rows = []
    for r in reqs:
        fs = sorted(by_req.get(r.id, []), key=lambda f: SEVERITY_ORDER.get(f.severity, 9))
        v = verifs[r.id]
        state = closure_state(r.verification_status, r.evidence)
        rows.append({
            **r.to_dict(),
            "score": quality_score(fs),
            "findings": [f.to_dict() for f in fs],
            "trace_findings": [f.to_dict() for f in trace_by.get(r.id, [])],
            "verification": v.to_dict(),
            "closure": state,
            "llm": r.llm,
        })
    sev = Counter(f.severity for f in findings)
    rules = Counter(f"{f.rule_id} {f.rule_name}" for f in findings)
    methods = Counter((r.method_override or verifs[r.id].primary) for r in reqs)
    clean = sum(1 for row in rows if not row["findings"])
    graph = link_graph(reqs)
    graph.pop("known", None)
    return {
        "tool": f"{PRODUCT_NAME} v{__version__}",
        "brand": public_brand(),
        "profile": profile.to_public_dict(),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "source": source_name,
        "disclaimer": DISCLAIMER,
        "summary": {
            "requirements": len(reqs),
            "findings": len(findings),
            "requirements_with_findings": len(reqs) - clean,
            "clean_requirements": clean,
            "by_severity": {k: sev.get(k, 0) for k in ("High", "Medium", "Low")},
            "by_rule": dict(rules.most_common()),
            "verification_methods": dict(methods.most_common()),
            "average_score": round(sum(r["score"] for r in rows) / len(rows), 1) if rows else 0,
            "closure": summarize(rows),
        },
        "requirements": rows,
        "trace": {"findings": [f.to_dict() for f in traces], "graph": graph},
        "insight": build_insight(rows, traces),
        "llm_used": any(r.llm for r in reqs),
    }


def requirements_from_mappings(rows: Optional[list]) -> List[Requirement]:
    from .extract import requirement_from_mapping
    return [requirement_from_mapping(row) for row in (rows or []) if str((row or {}).get("text") or "").strip()]
