"""Product name, taglines, and module names.

This is the only runtime definition of the user-facing name. A later rename
is a change to this file. Rendered pages, the CLI, exports, and the API read
these constants. Prose documents repeat them; tests/test_brand.py fails if
those copies drift.
"""
from __future__ import annotations

PRODUCT_NAME = "VeriReq"
WORDMARK_LEAD = "Veri"
WORDMARK_TAIL = "Req"
TAGLINE = "Engineering Intelligence"
TAGLINE_SECOND = "Intelligence behind every requirement."
VENDOR_LINE = "A product of Intelligent Design LLC"
SITE_URL = "https://verireq.intelligent-design.us"
REPO_URL = "https://github.com/intelligent-design-llc/verireq"
IMAGE_NAME = "verireq"
PACKAGE_NAME = "verireq"

# Stable ids for the interface. Labels are "VeriReq" plus the module name.
MODULES = (
    {"id": "spec", "name": "Spec", "summary": "Requirements development"},
    {"id": "analyze", "name": "Analyze", "summary": "Quality and consistency analysis"},
    {"id": "trace", "name": "Trace", "summary": "Traceability and dependency management"},
    {"id": "verify", "name": "Verify", "summary": "Verification and validation"},
    {"id": "insight", "name": "Insight", "summary": "Engineering intelligence"},
)


def module_label(module: dict) -> str:
    return f"{PRODUCT_NAME} {module['name']}"


def public_brand() -> dict:
    return {
        "product_name": PRODUCT_NAME,
        "wordmark_lead": WORDMARK_LEAD,
        "wordmark_tail": WORDMARK_TAIL,
        "tagline": TAGLINE,
        "tagline_second": TAGLINE_SECOND,
        "vendor_line": VENDOR_LINE,
        "site_url": SITE_URL,
        "repo_url": REPO_URL,
        "package_name": PACKAGE_NAME,
        "image_name": IMAGE_NAME,
        "modules": [{**m, "label": module_label(m)} for m in MODULES],
    }
