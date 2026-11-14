"""Closure tracking for verification.

A requirement is closed only when its status is Passed or Waived and an
evidence reference has been recorded. A Passed status with no evidence stays
open as 'Evidence missing'. Failed stays visible as its own state.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable

CLOSED_STATUSES = {"Passed", "Waived"}
ORDER = ["Open", "In progress", "Evidence missing", "Failed", "Closed"]


def closure_state(status: str, evidence: str) -> str:
    status = status or "Not started"
    has_evidence = bool((evidence or "").strip())
    if status == "Failed":
        return "Failed"
    if status in CLOSED_STATUSES and has_evidence:
        return "Closed"
    if status in CLOSED_STATUSES:
        return "Evidence missing"
    if status in {"Planned", "In progress"}:
        return "In progress"
    return "Open"


def summarize(rows: Iterable[dict]) -> dict:
    counts = Counter()
    total = 0
    for row in rows:
        total += 1
        counts[closure_state(row.get("verification_status") or "Not started", row.get("evidence") or "")] += 1
    closed = counts.get("Closed", 0)
    return {
        "total": total,
        "closed": closed,
        "percent": round(100 * closed / total, 1) if total else 0,
        "by_state": {name: counts.get(name, 0) for name in ORDER},
    }
