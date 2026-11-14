"""The product name is defined once and repeated in the documents readers see."""
from pathlib import Path

from verireq.brand import (
    PACKAGE_NAME,
    PRODUCT_NAME,
    REPO_URL,
    SITE_URL,
    TAGLINE,
    TAGLINE_SECOND,
    WORDMARK_LEAD,
    WORDMARK_TAIL,
    module_label,
    public_brand,
)

ROOT = Path(__file__).resolve().parent.parent


def test_brand_module_is_the_source():
    assert PRODUCT_NAME == "VeriReq"
    assert WORDMARK_LEAD + WORDMARK_TAIL == PRODUCT_NAME
    assert TAGLINE == "Engineering Intelligence"
    assert TAGLINE_SECOND == "Intelligence behind every requirement."
    assert PACKAGE_NAME == "verireq"
    assert SITE_URL == "https://copilot.intelligent-design.us"
    assert REPO_URL == "https://github.com/intelligent-design-llc/verireq"
    labels = [module_label(m) for m in public_brand()["modules"]]
    assert labels[3] == "VeriReq Verify"


def test_docs_and_ui_use_the_brand_and_not_the_old_product_name():
    docs = ["README.md", "ROADMAP.md", "NOTICE", "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md"]
    for name in docs:
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "ECSS Copilot" not in text, name
        assert "ecss-copilot" not in text, name
        assert "ecss_copilot" not in text, name
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert PRODUCT_NAME in readme and TAGLINE in readme and SITE_URL in readme and REPO_URL in readme
    assert "formerly" not in readme.lower()
    html = (ROOT / "verireq" / "static" / "index.html").read_text(encoding="utf-8")
    assert "ECSS Copilot" not in html
    assert "__WORDMARK_LEAD__" in html and "__TAGLINE__" in html
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert 'CMD ["python", "-m", "verireq"]' in docker and REPO_URL in docker and SITE_URL in docker
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "verireq:ci" in ci
    meta = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "verireq"' in meta and SITE_URL in meta and REPO_URL in meta
