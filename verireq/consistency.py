"""Duplicate and conflict checks that sit beside the shared quality rules.

The comparisons are lexical: shared wording and numeric bounds. They do not
understand design intent. Findings name the other requirement so a reviewer
can decide.
"""
from __future__ import annotations

import re
from typing import List

from .models import Finding, Requirement

_STOP = {
    "the", "a", "an", "of", "to", "and", "or", "for", "in", "on", "by", "with",
    "shall", "should", "will", "must", "may", "be", "is", "are", "its", "their",
    "that", "this", "from", "at", "as", "not", "than", "within", "into",
}

_UPPER = re.compile(
    r"\b(?:not exceed|no greater than|at most|less than|below|under|no more than)\s+"
    r"([-+]?\d+(?:\.\d+)?)\s*([A-Za-z%°µ/²³]+)?",
    re.I,
)
_LOWER = re.compile(
    r"\b(?:at least|no less than|greater than|more than|above|minimum of|not less than)\s+"
    r"([-+]?\d+(?:\.\d+)?)\s*([A-Za-z%°µ/²³]+)?",
    re.I,
)


def _tokens(text: str) -> set:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOP and len(w) > 1}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _subject(text: str) -> set:
    head = re.split(r"\b(?:shall|should|must|will|may)\b", text, maxsplit=1, flags=re.I)[0]
    return _tokens(head)


def _bounds(text: str):
    uppers = [(float(m.group(1)), (m.group(2) or "").lower()) for m in _UPPER.finditer(text)]
    lowers = [(float(m.group(1)), (m.group(2) or "").lower()) for m in _LOWER.finditer(text)]
    return uppers, lowers


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def _f(req, rule_id, name, sev, msg, sug, match=""):
    return Finding(req_id=req.id, rule_id=rule_id, rule_name=name, severity=sev, message=msg,
                   suggestion=sug, match=match)


def consistency_findings(reqs: List[Requirement]) -> List[Finding]:
    out: List[Finding] = []
    norms = [_norm(r.text) for r in reqs]
    token_sets = [_tokens(r.text) for r in reqs]
    subjects = [_subject(r.text) for r in reqs]
    bounds = [_bounds(r.text) for r in reqs]
    seen_pairs = set()

    for i, left in enumerate(reqs):
        for j in range(i + 1, len(reqs)):
            right = reqs[j]
            pair = (left.id, right.id)
            if pair in seen_pairs:
                continue
            if norms[i] and norms[i] == norms[j]:
                continue  # exact copy is DOC-02
            sim = _jaccard(token_sets[i], token_sets[j])
            if sim >= 0.72 and len(token_sets[i]) >= 4 and len(token_sets[j]) >= 4:
                seen_pairs.add(pair)
                out.append(_f(
                    right, "CON-01", "Near-duplicate statement", "Medium",
                    f"Wording is close to {left.id} (shared terms {sim:.0%}). The two statements may be the same need.",
                    "Merge them, or rewrite one so the difference in scope is explicit.",
                    left.id,
                ))
                continue
            if _jaccard(subjects[i], subjects[j]) < 0.5:
                continue
            clash = _bound_clash(bounds[i], bounds[j])
            if clash:
                seen_pairs.add(pair)
                out.append(_f(
                    right, "CON-02", "Contradictory bounds", "High",
                    f"Numeric bounds disagree with {left.id}: {clash}. Both cannot be met as written.",
                    "Keep one bound, or split the cases (modes, phases) so each statement has its own range.",
                    left.id,
                ))
                continue
            if _polarity_clash(left.text, right.text, token_sets[i], token_sets[j]):
                seen_pairs.add(pair)
                out.append(_f(
                    right, "CON-03", "Contradictory obligation", "High",
                    f"One statement requires behaviour that {left.id} prohibits, or the reverse.",
                    "Decide which obligation stands and retire or re-scope the other.",
                    left.id,
                ))
    return out


def _bound_clash(left, right) -> str:
    lu, ll = left
    ru, rl = right
    for hi, hu in lu:
        for lo, lu_ in rl:
            if hu == lu_ and lo > hi:
                unit = f" {hu}" if hu else ""
                return f"lower bound {lo:g}{unit} is above upper bound {hi:g}{unit}"
    for hi, hu in ru:
        for lo, lu_ in ll:
            if hu == lu_ and lo > hi:
                unit = f" {hu}" if hu else ""
                return f"lower bound {lo:g}{unit} is above upper bound {hi:g}{unit}"
    return ""


def _polarity_clash(a: str, b: str, ta: set, tb: set) -> bool:
    a_neg = bool(re.search(r"\bshall\s+not\b", a, re.I)) and not re.search(
        r"\bshall\s+not\s+(?:exceed|be\s+(?:less|more|greater|lower|higher))\b", a, re.I)
    b_neg = bool(re.search(r"\bshall\s+not\b", b, re.I)) and not re.search(
        r"\bshall\s+not\s+(?:exceed|be\s+(?:less|more|greater|lower|higher))\b", b, re.I)
    if a_neg == b_neg:
        return False
    return _jaccard(ta, tb) >= 0.55
