"""Extract individual requirements from uploaded documents or pasted text.

Supported: .txt/.md (or pasted text), .docx (paragraphs + tables), .pdf (text layer),
.csv, .xlsx, .reqif/.xml (best effort). Scanned PDFs (no text layer) are not supported.
"""
from __future__ import annotations

import csv
import io
import re
from typing import List, Optional, Tuple

from .models import Requirement

# Requirement IDs: letter prefix, at least one separator and a digit group,
# e.g. SYS-010, PIPIT-EPS-020, REQ_12, R-3.2.1, OBC.SW.004
ID_RE = re.compile(r"^\s*\[?((?=[A-Z0-9._-]*\d)[A-Z][A-Z0-9]*(?:[-_.][A-Z0-9]+)+)\]?\s*[:.)\-–]?\s+(.*)$")
NUM_ID_RE = re.compile(r"^\s*(\d+(?:\.\d+){1,6})\s+(.+)$")
SHALL_RE = re.compile(r"\bshall\b", re.I)
ID_HEADERS = ("id", "req id", "req. id", "requirement id", "identifier", "ref", "reference", "req #", "no.", "number", "key")
TEXT_HEADERS = ("requirement", "requirement text", "text", "statement", "description", "req text", "shall statement")


class ExtractionError(Exception):
    pass


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------

def _looks_like_heading(line: str) -> bool:
    s = line.strip()
    return bool(re.match(r"^(?:\d+(?:\.\d+)*\.?\s+)?[A-Z][\w /&()-]{0,60}$", s)) and not SHALL_RE.search(s) and len(s.split()) <= 8


MODAL_RE = re.compile(r"\b(?:shall|should|must|will|may)\b", re.I)


def _match_id_line(line: str):
    m = ID_RE.match(line)
    if m:
        return m.group(1), m.group(2)
    m = NUM_ID_RE.match(line)
    if m:
        return m.group(1), m.group(2)
    return None


def _is_req_body(body: str) -> bool:
    """Distinguish 'SYS-010 The X shall ...' from a heading like 'LARK-1 System Overview'."""
    b = body.strip()
    return bool(MODAL_RE.search(b)) or (len(b.split()) >= 6 and b.endswith("."))


def requirements_from_text(text: str, source_prefix: str = "line") -> List[Requirement]:
    lines = [l.rstrip() for l in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    reqs: List[Requirement] = []
    cur_id: Optional[str] = None
    cur_text: List[str] = []
    cur_src = ""

    def flush():
        nonlocal cur_id, cur_text
        if cur_id is not None:
            t = _clean(re.sub(r"(?<=[a-z])-\s+(?=[a-z])", "-", " ".join(cur_text)))
            if t:
                reqs.append(Requirement(id=cur_id, text=t, source=cur_src))
        cur_id, cur_text = None, []

    any_ids = any(_match_id_line(l) for l in lines)
    if any_ids:
        for i, line in enumerate(lines, 1):
            matched = _match_id_line(line)
            prev = lines[i - 2].rstrip() if i >= 2 else ""
            dangling = bool(re.search(r"(?:-|\b(?:the|a|an|of|for|and|or|to|with|in|on|by|from|at))$", prev, re.I))
            body = " ".join([matched[1]] + [l for l in lines[i:i + 3] if not _match_id_line(l)]) if matched else ""
            if matched and _is_req_body(body) and not dangling:
                flush()
                cur_id, cur_text, cur_src = matched[0], [matched[1]], f"{source_prefix} {i}"
            elif cur_id is not None:
                if not line.strip() or _looks_like_heading(line):
                    flush()
                elif re.match(r"^\s*(?:rationale|note|verification|comment)\s*[:\-]", line, re.I):
                    flush()  # stop at rationale/notes fields
                else:
                    cur_text.append(line.strip())
        flush()
        return reqs

    # No IDs: split into sentences and keep those containing "shall"
    paragraphs = re.split(r"\n\s*\n", text)
    n = 0
    for p_i, para in enumerate(paragraphs, 1):
        para = _clean(para.replace("\n", " "))
        for sent in re.split(r"(?<=[.;])\s+(?=[A-Z])", para):
            if re.search(r"\b(?:shall|should|must|will|may)\b", sent, re.I):
                n += 1
                reqs.append(Requirement(id=f"AUTO-{n:03d}", text=sent.strip(), source=f"paragraph {p_i}",
                                        id_generated=True))
    return reqs


def _clean(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s


# ---------------------------------------------------------------------------
# Tables (CSV/XLSX/DOCX tables)
# ---------------------------------------------------------------------------

def _pick_columns(header: List[str], rows: List[List[str]]) -> Tuple[Optional[int], Optional[int]]:
    h = [(_clean(str(c)) if c is not None else "").lower() for c in header]
    def _is_id_header(c: str) -> bool:
        if any(k in c for k in ("parent", "depend", "verif", "status", "evidence", "section", "topic", "method")):
            return False
        return c in ID_HEADERS or c.endswith(" id")

    id_col = next((i for i, c in enumerate(h) if _is_id_header(c)), None)
    text_col = next((i for i, c in enumerate(h) if c in TEXT_HEADERS), None)
    if text_col is None:
        text_col = next((i for i, c in enumerate(h) if any(t in c for t in ("requirement", "text", "statement", "description")) and i != id_col), None)
    if text_col is None and rows:
        # longest average text column
        widths = {}
        for r in rows:
            for i, c in enumerate(r):
                widths[i] = widths.get(i, 0) + len(str(c or ""))
        if widths:
            text_col = max(widths, key=widths.get)
    if id_col is None and rows:
        for i in range(len(header)):
            if i == text_col:
                continue
            vals = [str(r[i]) for r in rows if i < len(r) and r[i]]
            if vals and sum(bool(re.match(r"^[A-Z][A-Z0-9]*(?:[-_.][A-Z0-9]+)+$", v.strip())) for v in vals) >= 0.6 * len(vals):
                id_col = i
                break
    return id_col, text_col


def _header_index(header: List[str], pred) -> Optional[int]:
    h = [(_clean(str(c)) if c is not None else "").lower() for c in header]
    return next((i for i, c in enumerate(h) if pred(c)), None)


def requirements_from_table(header: List[str], rows: List[List[str]], source_prefix="row") -> List[Requirement]:
    id_col, text_col = _pick_columns(header, rows)
    if text_col is None:
        return []
    parent_col = _header_index(header, lambda c: "parent" in c)
    depends_col = _header_index(header, lambda c: "depend" in c)
    status_col = _header_index(header, lambda c: "status" in c)
    evidence_col = _header_index(header, lambda c: "evidence" in c)
    reqs = []
    n = 0
    for i, r in enumerate(rows, 2):
        text = _clean(str(r[text_col])) if text_col < len(r) and r[text_col] is not None else ""
        if not text:
            continue
        rid = _clean(str(r[id_col])) if id_col is not None and id_col < len(r) and r[id_col] else ""
        gen = False
        if not rid:
            n += 1
            rid, gen = f"AUTO-{n:03d}", True

        def cell(idx):
            if idx is None or idx >= len(r) or r[idx] is None:
                return ""
            return _clean(str(r[idx]))

        depends = [p.strip() for p in re.split(r"[,;]", cell(depends_col)) if p.strip()] if depends_col is not None else []
        reqs.append(Requirement(
            id=rid, text=text, source=f"{source_prefix} {i}", id_generated=gen,
            parent_id=cell(parent_col), depends_on=depends,
            verification_status=cell(status_col) or "Not started",
            evidence=cell(evidence_col),
        ))
    return reqs


def _table_is_requirements(header: List[str]) -> bool:
    h = " ".join(_clean(str(c)).lower() for c in header)
    return any(k in h for k in ("requirement", "statement", "text", "description")) or bool(re.search(r"\bid\b", h))


# ---------------------------------------------------------------------------
# Format readers
# ---------------------------------------------------------------------------

def from_csv(data: bytes) -> List[Requirement]:
    txt = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(txt[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(txt), dialect))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return []
    return requirements_from_table(rows[0], rows[1:])


def from_xlsx(data: bytes) -> List[Requirement]:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out: List[Requirement] = []
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        rows = [r for r in rows if any(c not in (None, "") for c in r)]
        if len(rows) < 2:
            continue
        reqs = requirements_from_table([str(c or "") for c in rows[0]], rows[1:], source_prefix=f"{ws.title} row")
        out.extend(reqs)
    return out


def from_docx(data: bytes) -> List[Requirement]:
    import docx
    d = docx.Document(io.BytesIO(data))
    reqs: List[Requirement] = []
    for t_i, table in enumerate(d.tables, 1):
        rows = [[_clean(c.text) for c in row.cells] for row in table.rows]
        if len(rows) >= 2 and _table_is_requirements(rows[0]):
            reqs.extend(requirements_from_table(rows[0], rows[1:], source_prefix=f"table {t_i} row"))
    para_text = "\n\n".join(p.text for p in d.paragraphs
                              if not (p.style is not None and p.style.name.lower().startswith(("heading", "title"))))
    para_reqs = requirements_from_text(para_text, source_prefix="paragraph")
    known = {r.id for r in reqs}
    para_reqs = [r for r in para_reqs if r.id not in known]
    if reqs:
        # generated IDs continue after any table-generated ones
        n = sum(1 for r in reqs if r.id_generated)
        for r in para_reqs:
            if r.id_generated:
                n += 1
                r.id = f"AUTO-{n:03d}"
    return reqs + para_reqs


def from_pdf(data: bytes) -> List[Requirement]:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    if not text.strip():
        raise ExtractionError("PDF has no text layer (scanned?). OCR is not supported in v0.1.")
    return requirements_from_text(text, source_prefix="pdf line")


def from_reqif(data: bytes) -> List[Requirement]:
    """ReqIF 1.x import. Reads requirement text, ids, parent and depends-on relations."""
    from .reqif import loads
    try:
        return loads(data)
    except ValueError as exc:
        raise ExtractionError(str(exc)) from exc


def requirement_from_mapping(row: dict) -> Requirement:
    depends = row.get("depends_on") or []
    if isinstance(depends, str):
        depends = [p.strip() for p in re.split(r"[,;]", depends) if p.strip()]
    reviews = row.get("reviews") or []
    external = row.get("external") or {}
    llm = row.get("llm") if isinstance(row.get("llm"), dict) else None
    status = str(row.get("verification_status") or "Not started").strip() or "Not started"
    return Requirement(
        id=str(row.get("id") or "").strip() or "AUTO-000",
        text=_clean(str(row.get("text") or "")),
        source=str(row.get("source") or ""),
        id_generated=bool(row.get("id_generated")),
        parent_id=str(row.get("parent_id") or "").strip(),
        depends_on=[str(d).strip() for d in depends if str(d).strip()],
        verification_status=status,
        method_override=str(row.get("method_override") or "").strip(),
        evidence=str(row.get("evidence") or "").strip(),
        reviews=list(reviews) if isinstance(reviews, list) else [],
        external=dict(external) if isinstance(external, dict) else {},
        llm=llm,
    )


def extract(filename: str, data: bytes) -> List[Requirement]:
    name = (filename or "").lower()
    if name.endswith(".docx"):
        reqs = from_docx(data)
    elif name.endswith(".pdf"):
        reqs = from_pdf(data)
    elif name.endswith(".csv") or name.endswith(".tsv"):
        reqs = from_csv(data)
    elif name.endswith((".xlsx", ".xlsm")):
        reqs = from_xlsx(data)
    elif name.endswith((".reqif", ".xml")):
        reqs = from_reqif(data)
    elif name.endswith((".txt", ".md")) or "." not in name:
        reqs = requirements_from_text(data.decode("utf-8", errors="replace"))
    else:
        raise ExtractionError(f"Unsupported file type: {filename}")
    return reqs
