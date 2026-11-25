# Roadmap

VeriReq is an early workbench. The product name may still change. The roadmap is indicative.

The running name is [`verireq/brand.py`](verireq/brand.py). Repository: [github.com/intelligent-design-llc/verireq](https://github.com/intelligent-design-llc/verireq). Site: [copilot.intelligent-design.us](https://copilot.intelligent-design.us).

## v0.2 (current)

- Standards profiles, with NASA systems engineering as the default and ECSS kept as one profile
- Five modules: Spec, Analyze, Trace, Verify, Insight. Verify tracks method, evidence, and closure
- ReqIF 1.1 import and export for tools such as DOORS, DOORS Next, and Polarion
- Optional Jira REST connector, off unless configured
- Xray JSON and JUnit file exchange, with no Xray account
- Local rule engine that runs with the model pass and Jira connector both off

## Planned integrations

These are not in the current build. The names belong to their owners. VeriReq is not affiliated with them and does not claim a certified connection.

- **IBM DOORS and DOORS Next.** A direct connector, separate from the ReqIF file exchange that ships today. DOORS Next would use OSLC Requirements Management. Classic DOORS would use a DXL or ReqIF path, because that client does not speak OSLC the same way.
- **MBSE links.** Dassault Cameo and MagicDraw would be reached through SysML v1 today and the SysML v2 API where a model exposes it. Eclipse Capella would be reached through its requirements viewpoint or a ReqIF bridge. A generic SysML v2 API client would cover other tools that implement that API.

## v0.3: compliance matrix

- Draft a compliance matrix (C / PC / NC / N/A plus justification) against a chosen standard
- **Bring your own standard:** the user uploads their own copy; the project never ships standard text
- Clause-level citations so a reviewer can check every statement
- Tailoring support (applicable / tailored / not applicable)

## v0.4: deeper interchange

- Richer ReqIF (enumerations, more attribute types, round-trip of reviewer ballots)
- Traceability diff between revisions
- Optional persistence with an explicit delete

## Deployment and data control

- The image can be built locally (`docker build -t verireq .`). Publishing an image is a separate decision
- Model endpoint stays the operator's choice, including a model on the same machine
- Controlled data stays local unless the model pass or the Jira connector is deliberately enabled

## Quality

- Larger synthetic evaluation set with expected findings per profile
- Per-rule enablement is already data; severity overrides are not
- More than two reviewers in one session

Suggestions are welcome; please open an issue. Do not include export-controlled or customer data.
