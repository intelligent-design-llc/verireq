"""FastAPI app: single-page UI + JSON API.

Uploads are processed in memory and are not stored. The Jira connector is
optional and stays off until its environment variables are set. Xray and
ReqIF interchange are local files; they do not call a vendor service.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from . import __version__
from . import llm
from .brand import IMAGE_NAME, PRODUCT_NAME, public_brand
from .core import analyse, requirements_from_mappings
from .export import to_xlsx
from .extract import ExtractionError, extract, requirement_from_mapping, requirements_from_text
from .limits import MAX_JIRA_BATCH, MAX_REQUIREMENTS, MAX_UPLOAD_BYTES
from .jira_connector import JiraError, config as jira_config, pull_statuses, push_requirements
from .library import suggest
from .models import Requirement
from .profiles import ProfileError, get_registry, resolve_profile
from .reqif import dumps as reqif_dumps
from .xray_connector import export_execution, export_junit, import_results

STATIC = Path(__file__).parent / "static"
DEMO_PATH = Path(__file__).parent / "data" / "demosat.json"
MAX_BYTES = MAX_UPLOAD_BYTES
_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

app = FastAPI(title=f"{PRODUCT_NAME}", version=__version__)


@app.middleware("http")
async def limit_request_body(request: Request, call_next):
    body = await request.body()
    if len(body) > MAX_BYTES:
        return JSONResponse({"detail": "Request too large (15 MB max)."}, status_code=413)
    return await call_next(request)

_TOKENS = None


def _tokens() -> dict:
    brand = public_brand()
    return {
        "__PRODUCT_NAME__": brand["product_name"],
        "__WORDMARK_LEAD__": brand["wordmark_lead"],
        "__WORDMARK_TAIL__": brand["wordmark_tail"],
        "__TAGLINE__": brand["tagline"],
        "__TAGLINE_SECOND__": brand["tagline_second"],
        "__VENDOR_LINE__": brand["vendor_line"],
    }


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


@app.get("/")
def index():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for key, value in _tokens().items():
        html = html.replace(key, _esc(value))
    return HTMLResponse(html)


@app.get("/mark.svg")
def mark():
    return FileResponse(STATIC / "mark.svg", media_type="image/svg+xml")


@app.get("/api/config")
def get_config():
    c = llm.config()
    jira = jira_config()
    return {
        "version": __version__,
        "brand": public_brand(),
        "default_profile": get_registry().default.id,
        "llm": {"enabled": c["enabled"], "base_url": c["base_url"], "model": c["model"]},
        "jira": {"enabled": jira["enabled"], "base_url": jira["base_url"], "project": jira["project"],
                 "issue_type": jira["issue_type"]},
        "xray": {"enabled": False, "file_exchange": True},
        "reqif": {"enabled": True},
    }


@app.get("/api/profiles")
def list_profiles():
    reg = get_registry()
    return {"default": reg.default.id, "profiles": reg.public_list()}


def _download_name(name: str) -> str:
    cleaned = _NAME_RE.sub("-", name).strip(".-")
    return cleaned or "download"


@app.get("/api/demo")
def demo_project():
    """Analysed fictional DemoSat set. No network call; the file ships with the package."""
    payload = json.loads(DEMO_PATH.read_text(encoding="utf-8"))
    reqs = requirements_from_mappings(payload["requirements"])
    if len(reqs) > MAX_REQUIREMENTS:
        raise HTTPException(422, "Demo set is larger than the analyser accepts.")
    return analyse(reqs, payload.get("source") or "DemoSat", payload.get("profile") or None)


@app.get("/api/library")
def library(q: str = ""):
    return {"suggestions": suggest(q)}


@app.post("/api/analyze")
async def analyze(request: Request):
    try:
        reqs, source, profile_id = await _read_requirements(request)
        profile = resolve_profile(profile_id)
    except ProfileError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ExtractionError as exc:
        raise HTTPException(422, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    if not reqs:
        raise HTTPException(422, "No requirements found. Requirements need an ID (for example SYS-010) or a binding "
                                  "'shall' statement, or a table with an ID and a requirement text column.")
    return analyse(reqs, source, profile)


@app.post("/api/llm")
async def llm_refine(result: dict):
    if not llm.config()["enabled"]:
        raise HTTPException(400, "LLM is not configured on the server (LLM_BASE_URL / LLM_MODEL).")
    try:
        return llm.refine(result)
    except ProfileError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"LLM call failed: {exc}") from exc


@app.post("/api/export")
async def export(result: dict):
    data = to_xlsx(result)
    profile = ((result.get("profile") or {}).get("id")) or "report"
    name = _download_name(f"{IMAGE_NAME}-{profile}-report.xlsx")
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/reqif")
async def export_reqif(result: dict):
    reqs = [requirement_from_mapping(r) for r in result.get("requirements") or []]
    profile = (result.get("profile") or {}).get("name") or PRODUCT_NAME
    data = reqif_dumps(reqs, title=f"{PRODUCT_NAME} — {profile}")
    name = _download_name(f"{IMAGE_NAME}-requirements.reqif")
    return Response(data, media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/xray/export")
async def xray_export(result: dict):
    reqs = [requirement_from_mapping(r) for r in result.get("requirements") or []]
    methods = {r["id"]: (r.get("verification") or {}).get("primary") for r in result.get("requirements") or []}
    project = jira_config()["project"]
    document = export_execution(reqs, project_key=project, method_for=lambda req: methods.get(req.id))
    name = _download_name(f"{IMAGE_NAME}-xray.json")
    body = json.dumps(document, indent=2).encode("utf-8")
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/xray/export-junit")
async def xray_export_junit(result: dict):
    reqs = [requirement_from_mapping(r) for r in result.get("requirements") or []]
    methods = {r["id"]: (r.get("verification") or {}).get("primary") for r in result.get("requirements") or []}
    xml = export_junit(reqs, method_for=lambda req: methods.get(req.id))
    name = _download_name(f"{IMAGE_NAME}-xray-junit.xml")
    return Response(xml.encode("utf-8"), media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/xray/import")
async def xray_import(request: Request):
    ctype = request.headers.get("content-type", "")
    filename = ""
    if "application/json" in ctype and "multipart" not in ctype:
        body = await request.json()
        raw = body.get("document")
        if not isinstance(raw, str):
            raw = json.dumps(body.get("document") or body)
        filename = body.get("filename") or ""
        updates = _parse_xray(raw, filename)
        return {"updates": updates}
    form = await request.form()
    upload = form.get("file")
    text = str(form.get("text") or "")
    if upload is not None and getattr(upload, "filename", None):
        data = await upload.read()
        if len(data) > MAX_BYTES:
            raise HTTPException(413, "File too large (15 MB max).")
        text = data.decode("utf-8", errors="replace")
        filename = upload.filename or ""
    if not text.strip():
        raise HTTPException(400, "Upload an Xray JSON execution file or a JUnit XML file.")
    return {"updates": _parse_xray(text, filename)}


@app.post("/api/jira/push")
async def jira_push(result: dict):
    if not jira_config()["enabled"]:
        raise HTTPException(400, "Jira connector is off. Set JIRA_BASE_URL, JIRA_API_TOKEN, and JIRA_PROJECT_KEY.")
    reqs = [requirement_from_mapping(r) for r in result.get("requirements") or []]
    if not reqs:
        raise HTTPException(400, "Nothing to push.")
    try:
        created = push_requirements(reqs)
    except JiraError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"created": created}


@app.post("/api/jira/pull")
async def jira_pull(payload: dict):
    if not jira_config()["enabled"]:
        raise HTTPException(400, "Jira connector is off. Set JIRA_BASE_URL, JIRA_API_TOKEN, and JIRA_PROJECT_KEY.")
    keys = [str(k).strip() for k in (payload.get("keys") or []) if str(k).strip()]
    if not keys:
        raise HTTPException(400, "Provide Jira issue keys to pull.")
    if len(keys) > MAX_JIRA_BATCH:
        raise HTTPException(400, f"Refusing to pull more than {MAX_JIRA_BATCH} issue keys at once.")
    try:
        return {"issues": pull_statuses(keys)}
    except JiraError as exc:
        raise HTTPException(502, str(exc)) from exc


def _parse_xray(raw: str, filename: str):
    try:
        return import_results(raw, filename)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


async def _read_requirements(request: Request):
    ctype = request.headers.get("content-type", "")
    profile_id = request.query_params.get("profile") or ""
    if "application/json" in ctype:
        body = await request.json()
        profile_id = body.get("profile") or profile_id
        if body.get("requirements"):
            rows = body["requirements"]
            if not isinstance(rows, list):
                raise HTTPException(400, "requirements must be a list.")
            if len(rows) > MAX_REQUIREMENTS:
                raise HTTPException(413, f"More than {MAX_REQUIREMENTS} requirements.")
            return requirements_from_mappings(rows), str(body.get("source") or "editor")[:200], profile_id
        text = str(body.get("text") or "")
        if not text.strip():
            raise HTTPException(400, "Upload a file or paste requirement text.")
        return requirements_from_text(text), "pasted text", profile_id
    form = await request.form()
    profile_id = str(form.get("profile") or profile_id)
    upload = form.get("file")
    text = str(form.get("text") or "")
    if upload is not None and getattr(upload, "filename", None):
        data = await upload.read()
        if len(data) > MAX_BYTES:
            raise HTTPException(413, "File too large (15 MB max in the prototype).")
        try:
            reqs = extract(upload.filename, data)
        except ExtractionError as exc:
            raise HTTPException(422, str(exc)) from exc
        return reqs, upload.filename, profile_id
    if text.strip():
        return requirements_from_text(text), "pasted text", profile_id
    raise HTTPException(400, "Upload a file or paste requirement text.")
