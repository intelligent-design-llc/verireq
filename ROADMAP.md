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
