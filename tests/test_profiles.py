"""Standards profiles, samples, and the default NASA behaviour."""
from pathlib import Path

import pytest

from verireq.core import analyse
from verireq.extract import extract
from verireq.models import Requirement
from verireq.profiles import ProfileError, get_registry, load_registry, resolve_profile
from verireq.verification import draft_verification

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
EXPECTED = ("nasa", "dod", "ccsds", "iso", "ecss")


def test_shipped_profiles_and_default():
    reg = get_registry()
    assert reg.default.id == "nasa"
    assert reg.ids() == list(EXPECTED)
    nasa = reg.get("nasa")
    assert [m["name"] for m in nasa.methods] == ["Test", "Analysis", "Inspection", "Demonstration"]
    assert [m["id"] for m in nasa.milestones if m["id"] in {"SRR", "MDR", "PDR", "CDR"}] == ["SRR", "MDR", "PDR", "CDR"]
    ecss = reg.get("ECSS")
    assert [m["name"] for m in ecss.methods] == ["Test", "Analysis", "Review of design", "Inspection"]
    dod = reg.get("dod")
    assert [m["name"] for m in dod.methods] == ["Inspection", "Analysis", "Demonstration", "Test"]
    with pytest.raises(ProfileError):
        reg.get("invented")


def test_modal_wording_follows_profile():
    from verireq.rules import check_requirement
    will = check_requirement(Requirement("SYS-010", "The radio will transmit telemetry at 4 kbps."), "nasa")
    hit = next(f for f in will if f.rule_id == "RQ-01")
    assert "statement of fact" in hit.message
    should = check_requirement(Requirement("3.2.2", "The vehicle should remain controllable."), "dod")
    hit = next(f for f in should if f.rule_id == "RQ-01")
    assert "recommendation" in hit.message
    must = check_requirement(Requirement("SYS-SW-010", "The flight software must be reliable."), "iso")
    assert any(f.rule_id == "RQ-01" and "non-preferred" in f.message for f in must)


def test_profile_specific_rules_and_clean_citations():
    from verireq.rules import check_all
    ccsds = check_all([
        Requirement("SL-TC-010", "The spacecraft shall accept telecommands from the ground segment."),
        Requirement("SL-TM-010", "The space link shall transfer telemetry as identified in CCSDS 131.0-B."),
    ], "ccsds")
    flagged = {f.req_id for f in ccsds if f.rule_id == "STD-CCSDS-01"}
    assert flagged == {"SL-TC-010"}
    iso = check_all([
        Requirement("SYS-DM-020", "The spacecraft shall re-enter the atmosphere within 25 years after end of mission."),
        Requirement("SYS-DM-010", "The spacecraft shall limit debris release consistent with ISO 24113."),
    ], "iso")
    flagged = {f.req_id for f in iso if f.rule_id == "STD-ISO-01"}
    assert flagged == {"SYS-DM-020"}
    dod = check_all([
        Requirement("3.6.1", "The unit shall comply with MIL-STD for electromagnetic compatibility."),
        Requirement("3.6.2", "The unit shall comply with MIL-STD-461 for electromagnetic compatibility."),
        Requirement("3.2.1", "The vehicle shall provide a 28 V bus."),
    ], "dod")
    bare = [f for f in dod if f.rule_id == "STD-DOD-01"]
    assert len(bare) == 1 and bare[0].req_id == "3.6.1"
    assert not any(f.rule_id == "DOC-04" and f.req_id == "3.2.1" for f in dod)


@pytest.mark.parametrize("name", [
    "nasa_requirements.csv", "dod_requirements.csv", "ccsds_requirements.csv",
    "iso_requirements.csv", "ecss_requirements.csv",
])
def test_each_profile_sample_runs_offline(name, monkeypatch):
    for key in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "JIRA_BASE_URL", "JIRA_API_TOKEN", "JIRA_PROJECT_KEY"):
        monkeypatch.delenv(key, raising=False)
    profile_id = name.split("_", 1)[0]
    reqs = extract(name, (SAMPLES / name).read_bytes())
    assert len(reqs) >= 6
    result = analyse(reqs, name, profile_id)
    assert result["profile"]["id"] == profile_id
    assert result["llm_used"] is False
    assert result["summary"]["requirements"] == len(reqs)
    assert result["requirements"][0]["verification"]["primary"]


def test_verification_methods_follow_the_profile():
    coding = "The software shall comply with the project coding standard."
    assert draft_verification(Requirement("SYS-SW-010", coding), "ecss").primary == "Review of design"
    assert draft_verification(Requirement("SYS-SW-010", coding), "nasa").primary == "Analysis"
    demo = "The spacecraft shall demonstrate a transition to safe mode when the operator sends the command."
    assert draft_verification(Requirement("SYS-OPS-010", demo), "nasa").primary == "Demonstration"
    bland = "The item shall be blue."
    assert draft_verification(Requirement("SYS-GEN-010", bland), "nasa").primary == "Analysis"
    assert draft_verification(Requirement("SYS-GEN-010", bland), "ecss").primary == "Review of design"


def test_new_profile_is_data_only(tmp_path):
    (tmp_path / "demo.yaml").write_text("""
schema: 1
id: demo
name: Demo profile
short_name: Demo
order: 1
default: true
summary: A profile added as data.
references:
  - number: DEMO-1
    title: Demo practice note
terminology:
  note: shall is binding in this demo profile.
  binding:
    verbs: [shall]
    label: requirement
verification:
  default_method: Test
  methods:
    - name: Test
      short: T
      cues: []
    - name: Analysis
      short: A
      cues: []
milestones:
  - id: SRR
    name: System Requirements Review
document_types:
  - id: spec
    name: Specification
identifiers:
  description: Any id.
  example: DEMO-1
  enforce: off
extra_rules:
  - id: STD-DEMO-01
    name: Mentions a widget
    severity: Low
    summary: The word widget appears.
    when:
      any_terms: [widget]
    message: Widget is only a demo trigger.
    suggestion: Remove the word if it was unintentional.
""", encoding="utf-8")
    reg = load_registry(tmp_path)
    from verireq.rules import check_requirement
    findings = check_requirement(Requirement("DEMO-1", "The bus shall power the widget."), reg.get("demo"))
    assert any(f.rule_id == "STD-DEMO-01" for f in findings)
    assert resolve_profile("nasa").id == "nasa"
