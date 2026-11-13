"""Local requirement library used for reuse suggestions.

The seed file is synthetic text written for this project. Nothing is fetched
from the network. Suggestions are token overlap, not a model judgement.
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path
from typing import List

_STOP = {
    "the", "a", "an", "of", "to", "and", "or", "for", "in", "on", "by", "with",
    "shall", "should", "will", "must", "may", "be", "is", "are", "its", "that",
    "this", "from", "at", "as", "within",
}

LIBRARY_PATH = Path(__file__).resolve().parent.parent / "library" / "examples.csv"


def _tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP and len(w) > 1}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@lru_cache(maxsize=1)
def load_library() -> tuple:
    rows = []
    if not LIBRARY_PATH.is_file():
        return tuple()
    with LIBRARY_PATH.open(encoding="utf-8", newline="") as fh:
        for rec in csv.DictReader(fh):
            text = (rec.get("Requirement") or rec.get("text") or "").strip()
            if not text:
                continue
            rows.append({
                "id": (rec.get("ID") or rec.get("id") or "").strip(),
                "text": text,
                "topic": (rec.get("Topic") or rec.get("topic") or "").strip(),
            })
    return tuple(rows)


def suggest(query: str, limit: int = 5) -> List[dict]:
    q = _tokens(query or "")
    if len(q) < 2:
        return []
    scored = []
    needle = re.sub(r"\W+", " ", (query or "").lower()).strip()
    for item in load_library():
        hay = _tokens(item["text"] + " " + item["topic"])
        score = _jaccard(q, hay)
        same = needle == re.sub(r"\W+", " ", item["text"].lower()).strip()
        if score < 0.12 and not same:
            continue
        scored.append({**item, "score": round(score, 3), "same": same})
    scored.sort(key=lambda r: (-r["score"], r["id"]))
    return scored[:limit]
