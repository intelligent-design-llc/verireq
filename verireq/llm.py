"""Optional LLM pass via any OpenAI-compatible Chat Completions endpoint.

Configured only through environment variables:
  LLM_BASE_URL  e.g. https://api.x.ai/v1, https://api.groq.com/openai/v1, http://localhost:11434/v1
  LLM_API_KEY   API key (may be empty for local servers)
  LLM_MODEL     model name
Nothing is sent anywhere unless all of LLM_BASE_URL and LLM_MODEL are set AND the user
explicitly triggers the LLM pass. Only flagged requirements are sent.
"""
from __future__ import annotations

import json
import os
import re
from typing import List

import httpx

from .profiles import ProfileError, resolve_profile


def _prompt(profile) -> str:
    methods = ", ".join(m["name"] for m in profile.methods)
    note = (profile.terminology.get("note") or "").strip()
    return f"""You are a senior space systems engineer reviewing requirements.
The selected standards profile is {profile.name} ({profile.id}).
{note}
Use "{profile.binding_verb}" for binding requirements. Keep the original intent and values.
If a value is unknown, keep a clearly marked placeholder like "[TBD: value, unit]" instead of inventing numbers.
If the requirement must be split, return the parts separated by " || ".
For each requirement return:
- "rewrite": an improved requirement text.
- "verification_method": one of {methods}.
- "rationale": one short sentence explaining the method choice.
Respond with JSON only: {{"items": [{{"id": "...", "rewrite": "...", "verification_method": "...", "rationale": "..."}}]}}"""


def config():
    base = os.environ.get("LLM_BASE_URL", "").strip().rstrip("/")
    model = os.environ.get("LLM_MODEL", "").strip()
    key = os.environ.get("LLM_API_KEY", "").strip()
    return {"enabled": bool(base and model), "base_url": base, "model": model, "has_key": bool(key)}


def _post(messages, cfg, timeout=120):
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("LLM_API_KEY", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {"model": cfg["model"], "messages": messages, "temperature": 0.2}
    r = httpx.post(f"{cfg['base_url']}/chat/completions", headers=headers, json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _parse(content: str):
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        raise ValueError("LLM did not return JSON")
    data = json.loads(m.group(0))
    return data.get("items", [])


def refine(result: dict, max_items: int = 60, batch: int = 15) -> dict:
    cfg = config()
    if not cfg["enabled"]:
        raise RuntimeError("LLM not configured (set LLM_BASE_URL and LLM_MODEL, plus LLM_API_KEY if needed).")
    try:
        profile = resolve_profile((result.get("profile") or {}).get("id"))
    except ProfileError:
        profile = resolve_profile(None)
    methods = profile.method_names()
    prompt = _prompt(profile)
    flagged = [r for r in result["requirements"]
               if any(str(f.get("rule_id", "")).startswith(("RQ", "CON")) for f in r["findings"])][:max_items]
    by_id = {r["id"]: r for r in result["requirements"]}
    errors: List[str] = []
    for i in range(0, len(flagged), batch):
        chunk = flagged[i:i + batch]
        payload = [{"id": r["id"], "text": r["text"],
                    "findings": [f"{f['rule_name']}: {f['match']}" for f in r["findings"]],
                    "draft_method": r["verification"]["primary"]} for r in chunk]
        try:
            content = _post([{"role": "system", "content": prompt},
                             {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], cfg)
            for item in _parse(content):
                row = by_id.get(str(item.get("id")))
                if not row:
                    continue
                method = item.get("verification_method")
                row["llm"] = {
                    "rewrite": item.get("rewrite", ""),
                    "verification_method": method if method in methods else None,
                    "rationale": item.get("rationale", ""),
                    "model": cfg["model"],
                }
        except Exception as e:  # keep rule-based results on any failure
            errors.append(f"batch {i // batch + 1}: {e}")
    result["llm_used"] = True
    result["llm_model"] = cfg["model"]
    result["llm_errors"] = errors
    return result
