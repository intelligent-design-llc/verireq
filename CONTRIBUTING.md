# Contributing to VeriReq

Thanks for your interest! Bug reports, false-positive reports, new rules and documentation fixes are all welcome.

## Ground rules
- **Never include real project data** in issues, tests or pull requests: no export-controlled (ITAR/EAR/dual-use), classified, proprietary or customer data. Use synthetic examples only.
- **Do not paste text from ECSS, ISO, CCSDS, MIL-STD, or other copyrighted standards.** Describe the principle in your own words and cite the document number if helpful. The product name and module names belong in `verireq/brand.py`.
- Be respectful; see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Reporting a false positive or false negative
Open an issue with:
1. the (synthetic) requirement text,
2. the finding you got or expected (rule ID, e.g. `RQ-10`),
3. why you think it is wrong.

## Development setup
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

## Adding a standards profile

- Add `profiles/<id>.yaml`. The file name and the `id` must match. Point `verification.method_set` at `profiles/method_sets/taid.yaml` or `tari.yaml`, or inline `verification.methods`.
- Extra checks are `extra_rules` entries with `when` / `unless` terms or regular expressions. The engine in `verireq/rules.py` evaluates them. A new profile does not need a Python change.
- Restart the process. `GET /api/profiles` and the profile picker both load the directory.
- Do not copy standard text into the file. Number and title only.

## Adding or changing a rule
- Rules live in `verireq/rules.py`, registered with the `@rule("RQ-nn", "Name")` decorator, and return a list of `Finding` objects.
- Every finding needs a severity (`High` / `Medium` / `Low`), a clear message and an actionable suggestion.
- Add tests to `tests/test_rules.py` for both a positive case **and** a negative case (text that must *not* trigger the rule).
- Update the rule catalogue in `README.md`.

## Pull requests
- Keep PRs focused. Make sure `pytest` passes; CI runs it on Python 3.11–3.13.
- By contributing, you agree that your contribution is licensed under the Apache License 2.0 (see `LICENSE`, section 5).
- Sign-off is optional; the commit author name you use will be public.
