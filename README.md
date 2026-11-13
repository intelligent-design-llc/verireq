# VeriReq

[![CI](https://github.com/intelligent-design-llc/verireq/actions/workflows/ci.yml/badge.svg)](https://github.com/intelligent-design-llc/verireq/actions/workflows/ci.yml) [![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

**Engineering Intelligence.** Intelligence behind every requirement.

A product of Intelligent Design LLC. Product site: [verireq.intelligent-design.us](https://verireq.intelligent-design.us).

VeriReq is a browser-based workbench for space-project requirements. Verification is the center of the product: each requirement is drafted to a method from the selected standards profile, then tracked until status and evidence close it. Quality checks, trace links, and a review dashboard sit beside that.

The product name, taglines, and module names live in [`verireq/brand.py`](verireq/brand.py). Source: [github.com/intelligent-design-llc/verireq](https://github.com/intelligent-design-llc/verireq).

> **Status:** v0.2. Expect false positives. The product name may still change after a trademark check.

## Export control and data handling

The checker runs fully on the machine you start. With the model pass left unconfigured and the Jira connector left unconfigured, requirement text is processed in memory and is not sent to a model provider or to Jira. That is the mode to use when the text is ITAR/EAR-controlled or otherwise export-controlled: nothing in the rule engine, the verification draft, the spreadsheet, the ReqIF file, or the Xray file calls out.

Confirm both connectors are off before you load controlled data:

- Do not set `LLM_BASE_URL` or `LLM_MODEL`.
- Do not set `JIRA_BASE_URL`, `JIRA_API_TOKEN`, or `JIRA_PROJECT_KEY`.
- The banner in the web UI says the model pass is off, and Verify says the Jira connector is off.
- `GET /api/config` reports `llm.enabled: false` and `jira.enabled: false`.

Xray and ReqIF interchange are files you download or upload. They do not contact Jira, Xray, DOORS, or Polarion. If you turn the model pass or the Jira connector on, requirement text is sent to the endpoint you configured. Do that only when the endpoint is allowed to receive the data.

## Modules

| Module | What it does |
|---|---|
| Spec | Author, edit, and import requirements. CSV, Excel, DOCX, PDF (text layer), and ReqIF. Reuse suggestions come from the local library in [`library/examples.csv`](library/examples.csv). |
| Analyze | Shared quality rules plus near-duplicate and contradiction checks. The rule wording follows the selected profile. A model rewrite is optional and off by default. |
| Trace | Parent and dependency links, a trace matrix, orphan and broken-link findings, and a dependency graph. |
| Verify | The primary module. Profile methods, evidence, status, and closure. A requirement closes only when status is Passed or Waived and an evidence reference is recorded. Workbook, ReqIF, and Xray files export from here. |
| Insight | Quality and closure metrics, prefix hotspots, and two-reviewer priority with a disagreement flag for a named review such as SRR or PDR. |

## Standards profiles

Profiles are YAML under [`profiles/`](profiles/). The shared checks stay in code. Terminology, verification methods, review names, identifier conventions, document types, and extra rules are data. Add a profile by dropping in a file and restarting; the API and the profile picker both read the directory.

| Profile | Id | Role |
|---|---|---|
| NASA systems engineering | `nasa` | **Default.** shall / should / will, TAID methods, SRR / MDR / PDR / CDR. Paraphrases public NASA practice. |
| DoD / Space Force (MIL-STD style) | `dod` | shall / should / may / will, Inspection / Analysis / Demonstration / Test, paragraph or prefixed ids. |
| CCSDS space-link and operations | `ccsds` | Flags telemetry, telecommand, packet, space-link, ground-segment, or mission-operations statements that do not name a CCSDS recommendation. |
| ISO space systems | `iso` | ISO/IEC modal practice. Flags debris, disposal, or passivation statements that do not cite ISO 24113. |
| ECSS technical requirements | `ecss` | The previous behaviour: Test, Analysis, Review of design, Inspection. |

References in each file are a document number and title only. Rule text is original. No standard text is included. NASA handbook material is public domain and is still paraphrased.

`POST /api/analyze` accepts a form field or JSON field `profile` (omit it for `nasa`). The JSON result, the web UI, and the workbook name the profile that was used.

## Integrations

These are interchange paths, not certified connections. **Jira, Xray, IBM DOORS, DOORS Next, and Siemens Polarion are trademarks of their owners. VeriReq is not affiliated with, endorsed by, or sponsored by those owners.**

| Path | How it works | Default |
|---|---|---|
| ReqIF 1.1 | Import and export a requirements file with parent and depends-on relations. This is the interchange format tools such as DOORS, DOORS Next, and Polarion can exchange. | Local file. No account. |
| Jira | REST API v3. Push requirements as issues and pull status back. Base URL, API token, and project key come from the environment. | **Off** until `JIRA_BASE_URL`, `JIRA_API_TOKEN`, and `JIRA_PROJECT_KEY` are set. |
| Xray | Export a JSON execution document (Manual `testInfo`, Cloud status names) and a JUnit file using the property names in Xray's JUnit extension (`test_key`, `requirements`). Import either shape, or the Server/DC status names `PASS` / `FAIL`, to update verification status. | Local file. No Xray account and no network call. |

There is no live Xray subscription in this build, and no claim that a vendor has certified the mapping.

## Quickstart

Requires Python 3.10 or later.

```bash
git clone https://github.com/intelligent-design-llc/verireq.git
cd verireq
./run.sh                      # creates .venv on first run, then serves http://127.0.0.1:8000
```

Manual alternative:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m verireq
```

Try the synthetic sets in [`samples/`](samples/). `LARK-1_SRS_sample.*` is the original fictional sample. `nasa_requirements.csv`, `dod_requirements.csv`, `ccsds_requirements.csv`, `iso_requirements.csv`, and `ecss_requirements.csv` are new sets written for each profile.

### Docker

```bash
docker build -t verireq .
docker run --rm -p 127.0.0.1:8000:8000 verireq
```

The app has **no authentication**. Keep it bound to localhost, or put it behind an authenticating reverse proxy if you expose it on a network.

## Model pass (optional)

Without these variables the app is rule-based only and nothing leaves the machine.

| Variable | Example | Notes |
|---|---|---|
| `LLM_BASE_URL` | `http://localhost:11434/v1` | Any OpenAI-compatible Chat Completions base URL |
| `LLM_API_KEY` | `...` | Optional for local servers |
| `LLM_MODEL` | `llama3.1:70b` | Model name as the endpoint expects it |

If a call fails, the rule-based result is kept. Only requirements with quality findings are sent, and only after you confirm in the UI.

## Rule catalogue

Shared checks, with modal wording taken from the selected profile:

| ID | Check | Severity |
|---|---|---|
| RQ-01 | Missing binding verb | High |
| RQ-02 | Multiple binding verbs in one statement | High |
| RQ-03 | Vague or subjective term | High (Low for mild terms) |
| RQ-04 | Open item: TBD / TBC / TBS | High |
| RQ-05 | Escape clause | High |
| RQ-06 | Unverifiable absolute | High |
| RQ-07 | Weak or mixed modal verb | Medium |
| RQ-08 | Missing subject / passive voice without an agent | High / Low |
| RQ-09 | "and/or" or an ambiguous slash | High / Low |
| RQ-10 | Number without a unit | Medium |
| RQ-11 | Open-ended list | Medium |
| RQ-12 | Negative requirement | Low |
| RQ-13 | Statement too long | Low |
| RQ-14 | Ambiguous pronoun | Low |
| RQ-15 | Design solution stated as a requirement | Low |
| DOC-01 | Duplicate requirement ID | High |
| DOC-02 | Duplicate requirement text | Medium |
| DOC-03 | Missing requirement ID | Medium |
| DOC-04 | Identifier outside the profile convention | Low |
| CON-01 | Near-duplicate statement | Medium |
| CON-02 | Contradictory bounds | High |
| CON-03 | Contradictory obligation | High |
| TRACE-01 | Broken parent link | High |
| TRACE-02 | Broken dependency | High |
| TRACE-03 | Orphan requirement (only when the set uses links) | Medium |

Profile-only checks: `STD-DOD-01`, `STD-CCSDS-01`, `STD-ISO-01`. Descriptions are in the profile files.

## Development

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

```
verireq/        Python package. brand.py is the product-name source.
profiles/       standards profiles and verification cue sets
library/        local reuse examples
tests/          pytest
samples/        synthetic requirement sets
```

## Limitations

- Heuristic and English-only. Expect false positives and missed contradictions.
- PDFs need a text layer. ReqIF covers the interchange subset this tool writes and reads, not every vendor extension.
- Jira push uses issue type `Task` unless `JIRA_ISSUE_TYPE` is set. Status pull maps common Jira status names; it is not a workflow sync.
- Xray `requirementKeys` in the export are requirement ids from this tool until you link them to Jira issue keys.
- No accounts, no persistence on the server. The browser holds the working set.
- Profiles are not a certification of compliance to the named standard.

## Roadmap

See [ROADMAP.md](ROADMAP.md).

## License

Apache License 2.0, © 2026 Intelligent Design LLC. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
