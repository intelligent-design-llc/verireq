"""Quality metrics, risk hotspots, and multi-reviewer disagreement.

Reviewer names are whatever the session sends. The checker does not assign
people. A disagreement is two ballots on the same review milestone that do
not share a priority or a disposition.
"""
from __future__ import annotations

import re
from typing import List

from .models import Requirement


def _prefix(req_id: str) -> str:
    parts = re.split(r"[-_.]", req_id)
    if len(parts) >= 2 and not parts[0].isdigit():
        return parts[0]
    if re.match(r"\d+(?:\.\d+)+$", req_id):
        return parts[0]
    return parts[0] or req_id


def disagreement_keys(reviews: list) -> List[str]:
    groups = {}
    for rev in reviews or []:
        if not isinstance(rev, dict):
            continue
        key = str(rev.get("review") or "").strip().upper() or "(no review named)"
        groups.setdefault(key, []).append(rev)
    flags = []
    for key, items in groups.items():
        if len(items) < 2:
            continue
        priorities = {str(i.get("priority") or "").strip() for i in items if str(i.get("priority") or "").strip()}
        dispositions = {str(i.get("disposition") or "").strip() for i in items if str(i.get("disposition") or "").strip()}
        if len(priorities) > 1 or len(dispositions) > 1:
            flags.append(key)
    return flags


def build_insight(rows: List[dict], trace_findings: list) -> dict:
    """``rows`` are the analysed requirement dicts (score, findings, reviews)."""
    hotspots = {}
    attention = []
    disagreements = 0
    for row in rows:
        flags = disagreement_keys(row.get("reviews") or [])
        if flags:
            disagreements += 1
        high = sum(1 for f in row.get("findings") or [] if f.get("severity") == "High")
        trace_n = sum(1 for f in trace_findings if f.req_id == row["id"])
        score = row.get("score", 100)
        weight = (100 - score) + 15 * high + (40 if flags else 0) + 10 * trace_n
        reasons = []
        if high:
            reasons.append(f"{high} high finding(s)")
        if flags:
            reasons.append("reviewers disagree at " + ", ".join(flags))
        if trace_n:
            reasons.append(f"{trace_n} open trace finding(s)")
        if score < 80 and not reasons:
            reasons.append("quality score below 80")
        attention.append({
            "id": row["id"],
            "score": score,
            "attention": weight,
            "disagreement": bool(flags),
            "reviews_disagree_at": flags,
            "reasons": reasons,
        })
        bucket = hotspots.setdefault(_prefix(row["id"]), {"prefix": _prefix(row["id"]), "count": 0, "score_sum": 0, "high": 0})
        bucket["count"] += 1
        bucket["score_sum"] += score
        bucket["high"] += high
    hotspot_rows = []
    for bucket in hotspots.values():
        avg = round(bucket["score_sum"] / bucket["count"], 1) if bucket["count"] else 0
        if bucket["count"] >= 1 and (avg < 85 or bucket["high"]):
            hotspot_rows.append({
                "prefix": bucket["prefix"],
                "count": bucket["count"],
                "average_score": avg,
                "high": bucket["high"],
            })
    hotspot_rows.sort(key=lambda h: (h["average_score"], -h["high"]))
    attention.sort(key=lambda a: (-a["attention"], a["id"]))
    unverified = sum(1 for row in rows if (row.get("verification_status") or "Not started") not in {"Passed", "Waived"})
    return {
        "disagreements": disagreements,
        "trace_open": len(trace_findings),
        "unverified": unverified,
        "hotspots": hotspot_rows[:8],
        "attention": attention[:12],
    }
