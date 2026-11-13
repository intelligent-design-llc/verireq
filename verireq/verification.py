"""Heuristic draft of a verification method per requirement.

Cue patterns and method names come from the selected standards profile
(``profiles/method_sets``). The score is a draft for an engineer to confirm.
"""
from __future__ import annotations

from typing import List, Optional

from .models import Requirement, Verification
from .profiles import Profile, resolve_profile


def score_methods(text: str, profile: Optional[Profile] = None):
    return resolve_profile(profile).score_methods(text)


def draft_verification(req: Requirement, profile=None) -> Verification:
    profile = resolve_profile(profile)
    scores = profile.score_methods(req.text)
    order = profile.method_names()
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1][0], order.index(kv[0])))
    m1, (s1, why1) = ranked[0]
    if len(ranked) > 1:
        m2, (s2, why2) = ranked[1]
    else:
        m2, s2, why2 = m1, 0, []
    if s1 == 0:
        return Verification(
            req.id, profile.default_method, None,
            f"No strong cue found; defaulting to {profile.default_method}. Engineer to confirm.",
        )
    secondary = m2 if s2 >= 3 and s2 >= s1 * 0.5 else None
    rationale = f"{m1}: {', '.join(why1)}"
    if secondary:
        rationale += f". Secondary {secondary}: {', '.join(why2)}"
    return Verification(req.id, m1, secondary, rationale)


def draft_all(reqs: List[Requirement], profile=None) -> List[Verification]:
    profile = resolve_profile(profile)
    return [draft_verification(r, profile) for r in reqs]
