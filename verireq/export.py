"""Excel export: Summary, Requirements, Findings, Verification Matrix, Closure, Trace, Rules."""
from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .brand import PRODUCT_NAME
from .closure import ORDER
from .models import VERIFICATION_STATUSES
from .profiles import resolve_profile
from .rules import rule_catalogue

HEAD_FILL = PatternFill("solid", fgColor="0C2340")
HEAD_FONT = Font(bold=True, color="FFFFFF")
WARN_FILL = PatternFill("solid", fgColor="FFF4CE")
SEV_FILL = {"High": PatternFill("solid", fgColor="F8D7DA"), "Medium": PatternFill("solid", fgColor="FFE8C2"),
            "Low": PatternFill("solid", fgColor="E2EEF9")}
THIN = Side(style="thin", color="BBBBBB")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")


def _profile_view(result: dict) -> dict:
    embedded = result.get("profile") if isinstance(result.get("profile"), dict) else {}
    if embedded.get("verification_methods"):
        return embedded
    try:
        return resolve_profile((embedded or {}).get("id")).to_public_dict()
    except Exception:
        return resolve_profile(None).to_public_dict()


def _sheet(wb, title, headers, widths):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
        c = ws.cell(row=1, column=i)
        c.fill, c.font, c.alignment, c.border = HEAD_FILL, HEAD_FONT, Alignment(wrap_text=True, vertical="center"), BORDER
    ws.freeze_panes = "B2"
    return ws


def _finish(ws):
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment, c.border = WRAP, BORDER
    if ws.max_row > 1:
        ws.auto_filter.ref = ws.dimensions


def to_xlsx(result: dict) -> bytes:
    profile = _profile_view(result)
    methods = profile.get("verification_methods") or []
    wb = Workbook()
    wb.properties.creator = PRODUCT_NAME
    wb.properties.title = f"{PRODUCT_NAME} verification report (advisory draft)"
    s = wb.active
    s.title = "Summary"
    s.column_dimensions["A"].width = 36
    s.column_dimensions["B"].width = 96
    s.append([f"{PRODUCT_NAME} — verification, quality, and closure draft"])
    s["A1"].font = Font(bold=True, size=14, color="0C2340")
    s.append(["DISCLAIMER", result.get("disclaimer", "")])
    s["A2"].font = Font(bold=True, color="9C0006")
    s["B2"].fill = WARN_FILL
    s["B2"].alignment = WRAP
    s.row_dimensions[2].height = 72
    sm = result.get("summary") or {}
    closure = sm.get("closure") or {}
    refs = "; ".join(f"{r.get('number')} — {r.get('title')}" for r in profile.get("references") or [])
    rows = [
        ("Tool", result.get("tool", PRODUCT_NAME)),
        ("Standard profile", f"{profile.get('name', '')} ({profile.get('id', '')})"),
        ("Profile references", refs),
        ("Generated", result.get("generated_at", "")),
        ("Source", result.get("source", "")),
        ("Requirements extracted", sm.get("requirements", 0)),
        ("Total findings", sm.get("findings", 0)),
        ("Requirements with findings", sm.get("requirements_with_findings", 0)),
        ("Requirements with no findings", sm.get("clean_requirements", 0)),
        ("Findings - High", (sm.get("by_severity") or {}).get("High", 0)),
        ("Findings - Medium", (sm.get("by_severity") or {}).get("Medium", 0)),
        ("Findings - Low", (sm.get("by_severity") or {}).get("Low", 0)),
        ("Average quality score (0-100)", sm.get("average_score", 0)),
        ("Verification closure", f"{closure.get('closed', 0)}/{closure.get('total', 0)} closed ({closure.get('percent', 0)}%)"),
        ("LLM pass", f"yes ({result.get('llm_model')})" if result.get("llm_used") else "no (rule-based only)"),
        ("Jira connector", "not used by this export"),
    ]
    for r in rows:
        s.append(list(r))
    s.append([])
    s.append(["Closure state", "Count"])
    for name in ORDER:
        s.append([name, (closure.get("by_state") or {}).get(name, 0)])
    s.append([])
    s.append(["Findings by rule", "Count"])
    s.cell(row=s.max_row, column=1).font = Font(bold=True)
    for k, v in (sm.get("by_rule") or {}).items():
        s.append([k, v])
    s.append([])
    s.append(["Draft verification methods", "Count"])
    s.cell(row=s.max_row, column=1).font = Font(bold=True)
    for k, v in (sm.get("verification_methods") or {}).items():
        s.append([k, v])

    req = _sheet(wb, "Requirements",
                 ["Req ID", "Requirement text", "Source location", "Quality score", "# High", "# Medium", "# Low",
                  "Draft method", "Status", "Evidence", "Closure", "Parent", "Depends on",
                  "Suggested rewrite (LLM)", "Reviewer decision", "Reviewer comment"],
                 [16, 70, 16, 10, 8, 9, 8, 18, 16, 36, 18, 16, 20, 50, 18, 30])
    dv = DataValidation(type="list", formula1='"Accept,Accept with changes,Reject,Clarify"', allow_blank=True)
    req.add_data_validation(dv)
    status_dv = DataValidation(type="list", formula1='"' + ",".join(VERIFICATION_STATUSES) + '"', allow_blank=True)
    req.add_data_validation(status_dv)
    for r in result.get("requirements") or []:
        cnt = {k: sum(1 for f in r.get("findings") or [] if f.get("severity") == k) for k in ("High", "Medium", "Low")}
        llm = r.get("llm") or {}
        primary = r.get("method_override") or (r.get("verification") or {}).get("primary") or ""
        req.append([
            r.get("id"), r.get("text"), r.get("source"), r.get("score"), cnt["High"], cnt["Medium"], cnt["Low"],
            primary, r.get("verification_status") or "Not started", r.get("evidence") or "", r.get("closure") or "",
            r.get("parent_id") or "", ", ".join(r.get("depends_on") or []),
            llm.get("rewrite", ""), "", "",
        ])
        dv.add(f"O{req.max_row}")
        status_dv.add(f"I{req.max_row}")
        sc = req.cell(row=req.max_row, column=4)
        score = r.get("score") or 0
        sc.fill = SEV_FILL["High"] if score < 50 else SEV_FILL["Medium"] if score < 80 else PatternFill("solid", fgColor="D4EDDA")
    _finish(req)

    fnd = _sheet(wb, "Findings",
                 ["Req ID", "Rule", "Check", "Severity", "Triggered by", "Finding", "Suggested fix", "Requirement text"],
                 [16, 12, 32, 10, 22, 60, 60, 60])
    text_by_id = {r.get("id"): r.get("text") for r in result.get("requirements") or []}
    for r in result.get("requirements") or []:
        for f in r.get("findings") or []:
            fnd.append([f.get("req_id"), f.get("rule_id"), f.get("rule_name"), f.get("severity"), f.get("match"),
                        f.get("message"), f.get("suggestion"), r.get("text")])
            fnd.cell(row=fnd.max_row, column=4).fill = SEV_FILL.get(f.get("severity"), SEV_FILL["Low"])
    _finish(fnd)

    shorts = [m.get("short") or m.get("name") for m in methods]
    vm = _sheet(
        wb, "Verification Matrix",
        ["Req ID", "Requirement text", *shorts, "Primary method", "Secondary method", "Status", "Evidence", "Closure",
         "Rationale", "Method source", "Verification level", "Stage"],
        [16, 64] + [5] * len(shorts) + [18, 18, 16, 36, 18, 50, 14, 28, 28],
    )
    col = {m["name"]: 3 + i for i, m in enumerate(methods)}
    for r in result.get("requirements") or []:
        v = r.get("verification") or {}
        llm = r.get("llm") or {}
        primary = llm.get("verification_method") or r.get("method_override") or v.get("primary") or ""
        src = "LLM" if llm.get("verification_method") else ("override" if r.get("method_override") else "rule-based")
        rationale = llm.get("rationale") or v.get("rationale") or ""
        marks = [""] * len(methods)
        row = [r.get("id"), r.get("text"), *marks, primary, v.get("secondary") or "",
               r.get("verification_status") or "Not started", r.get("evidence") or "", r.get("closure") or "",
               rationale, src, profile.get("level_hint") or "", profile.get("stage_hint") or ""]
        if primary in col:
            row[col[primary] - 1] = "X"
        secondary = v.get("secondary")
        if secondary and secondary != primary and secondary in col:
            row[col[secondary] - 1] = "(x)"
        vm.append(row)
    _finish(vm)
    legend = ", ".join(f"{m.get('short')} = {m.get('legend') or m.get('name')}" for m in methods)
    vm.append([])
    vm.append(["Legend", legend + ". X = proposed primary method, (x) = proposed secondary method. All entries are drafts."])
    vm.append(["Profile", f"{profile.get('name')} ({profile.get('id')}). {profile.get('verification_note') or ''}"])

    cl = _sheet(wb, "Closure",
                ["Req ID", "Method", "Status", "Evidence", "Closure", "What is still open"],
                [16, 20, 16, 50, 18, 55])
    for r in result.get("requirements") or []:
        state = r.get("closure") or ""
        note = ""
        if state == "Evidence missing":
            note = "Status is Passed or Waived but no evidence reference is recorded."
        elif state == "Failed":
            note = "Verification failed. Record the failed evidence and the next action."
        elif state == "Open":
            note = "No verification activity recorded yet."
        elif state == "In progress":
            note = "Activity is planned or underway. Closure still needs a passed or waived status and evidence."
        elif state == "Closed":
            note = "Status and evidence are both recorded."
        method = r.get("method_override") or (r.get("verification") or {}).get("primary") or ""
        cl.append([r.get("id"), method, r.get("verification_status"), r.get("evidence"), state, note])
    _finish(cl)

    tr = _sheet(wb, "Trace",
                ["Req ID", "Parent", "Depends on", "Finding", "Severity", "Detail"],
                [16, 16, 24, 28, 12, 70])
    trace_by = {}
    for f in (result.get("trace") or {}).get("findings") or []:
        trace_by.setdefault(f.get("req_id"), []).append(f)
    for r in result.get("requirements") or []:
        found = trace_by.get(r.get("id")) or []
        if not found:
            tr.append([r.get("id"), r.get("parent_id"), ", ".join(r.get("depends_on") or []), "", "", ""])
            continue
        for f in found:
            tr.append([r.get("id"), r.get("parent_id"), ", ".join(r.get("depends_on") or []),
                       f.get("rule_name"), f.get("severity"), f.get("message")])
    _finish(tr)

    rc = _sheet(wb, "Rules", ["Rule ID", "Check", "Summary"], [14, 42, 80])
    try:
        catalogue = rule_catalogue(profile.get("id"))
    except Exception:
        catalogue = []
    for c in catalogue:
        rc.append([c["rule_id"], c["name"], c.get("doc") or ""])
    _finish(rc)

    # text_by_id kept for callers that expect the findings sheet to be self-contained
    _ = text_by_id
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
