"""Run the demo: start the app, upload the sample spec through the UI, take a screenshot,
download the XLSX via the Export button, and write a JSON summary.

Requires: pip install playwright && playwright install chromium
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo"
SAMPLE = ROOT / "samples" / "LARK-1_SRS_sample.docx"
PORT = int(os.environ.get("DEMO_PORT", "8765"))
URL = f"http://127.0.0.1:{PORT}"


def main():
    DEMO.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("LLM_")}  # demo = rule-based only
    env["PORT"] = str(PORT)
    srv = subprocess.Popen([sys.executable, "-m", "verireq"], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        for _ in range(50):
            try:
                if httpx.get(URL + "/api/config", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        with sync_playwright() as p:
            b = p.chromium.launch()
            page = b.new_page(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
            page.goto(URL)
            page.set_input_files("#file", str(SAMPLE))
            page.wait_for_selector("#verify-rows tr")
            page.wait_for_timeout(300)
            page.screenshot(path=str(DEMO / "ui_overview.png"), full_page=True)
            page.click("#tab-analyze")
            page.wait_for_selector("#findings tr")
            page.screenshot(path=str(DEMO / "ui_high_findings.png"), full_page=True)
            page.click("#tab-verify")
            with page.expect_download() as dl:
                page.click("#xlsx")
            dl.value.save_as(str(DEMO / "LARK-1_verireq-report.xlsx"))
            b.close()
        res = httpx.post(URL + "/api/analyze", files={"file": (SAMPLE.name, SAMPLE.read_bytes())}).json()
        (DEMO / "summary.json").write_text(json.dumps(res["summary"], indent=2))
        print(json.dumps(res["summary"], indent=2))
    finally:
        srv.terminate()
        srv.wait()


if __name__ == "__main__":
    main()
