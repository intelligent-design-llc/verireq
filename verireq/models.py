from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Requirement:
    id: str
    text: str
    source: str = ""          # e.g. "table row 4", "paragraph 12", "line 30"
    id_generated: bool = False  # True if we had to invent the ID
    parent_id: str = ""
    depends_on: list = field(default_factory=list)
    verification_status: str = "Not started"
    method_override: str = ""
    evidence: str = ""
    reviews: list = field(default_factory=list)  # {reviewer, review, priority, disposition}
    external: dict = field(default_factory=dict)  # {"jira": "PROJ-1"}
    llm: Optional[dict] = None

    def to_dict(self):
        data = asdict(self)
        data["depends_on"] = list(self.depends_on)
        data["reviews"] = list(self.reviews)
        return data


@dataclass
class Finding:
    req_id: str
    rule_id: str
    rule_name: str
    severity: str        # "High" | "Medium" | "Low"
    message: str
    suggestion: str
    match: str = ""      # text fragment that triggered the rule

    def to_dict(self):
        return asdict(self)


@dataclass
class Verification:
    req_id: str
    primary: str                 # "Test" | "Analysis" | "Inspection" | "Review of design"
    secondary: Optional[str]
    rationale: str
    source: str = "rule-based"   # or "llm"

    def to_dict(self):
        return asdict(self)


SEVERITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}
SEVERITY_PENALTY = {"High": 25, "Medium": 10, "Low": 4}
# Historical ECSS method list. Live analyses use the selected profile's methods.
METHODS = ["Test", "Analysis", "Inspection", "Review of design"]
VERIFICATION_STATUSES = ["Not started", "Planned", "In progress", "Passed", "Failed", "Waived"]
REVIEW_PRIORITIES = ["High", "Medium", "Low"]
REVIEW_DISPOSITIONS = ["Accept", "Accept with changes", "Reject", "Clarify"]
