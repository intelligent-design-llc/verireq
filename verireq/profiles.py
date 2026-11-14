"""Load standards profiles from YAML.

Profiles live in the repository ``profiles/`` directory, next to the
``verireq`` package. A profile is data: terminology, verification
methods, review names, identifier conventions, document types, and optional
extra rules. Shared rule logic stays in ``rules.py`` and ``verification.py``.

Adding a standard is a new YAML file. Restart the process and the API and
the web UI both pick it up. Files whose names start with ``_`` and the
``method_sets/`` directory are not profiles.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

import yaml

MODAL_GROUPS = ("binding", "goal", "fact", "permission", "possibility", "discouraged", "other_weak")
SEVERITIES = {"High", "Medium", "Low"}
_NONBINDING_ORDER = ("discouraged", "goal", "fact", "permission", "possibility", "other_weak")


class ProfileError(ValueError):
    """A profile file is missing, unknown, or internally inconsistent."""


def profiles_root() -> Path:
    return Path(__file__).resolve().parent.parent / "profiles"


class Profile:
    """One standards profile. Cue regexes stay on the object; the public dict does not."""

    def __init__(self, data: dict, methods: List[dict]):
        self.data = data
        self.id = data["id"]
        self.name = data["name"]
        self.short_name = data.get("short_name") or self.id.upper()
        self.audience = data.get("audience") or ""
        self.summary = data["summary"].strip()
        self.order = int(data.get("order", 1000))
        self.is_default = bool(data.get("default", False))
        self.references = list(data.get("references") or [])
        self.terminology = data["terminology"]
        self.milestones = list(data.get("milestones") or [])
        self.document_types = list(data.get("document_types") or [])
        self.identifiers = data["identifiers"]
        self.verification = data["verification"]
        self.parameters = data.get("parameters") or {}
        self.vocabulary = data.get("vocabulary") or {}
        self.extra_rules = list(data.get("extra_rules") or [])
        self.methods = methods
        rule_set = data.get("rule_set") or {}
        self.rule_shared = rule_set.get("shared", "all")
        self.rule_disabled = set(rule_set.get("disabled") or [])
        self._id_pattern = None
        pattern = self.identifiers.get("pattern") or ""
        if pattern:
            self._id_pattern = re.compile(pattern)
        self._cues = []
        for method in methods:
            compiled = []
            for cue in method.get("cues") or []:
                compiled.append((re.compile(cue["pattern"], re.I), int(cue["weight"]), cue["cue"]))
            self._cues.append((method["name"], compiled))

    # -- terminology -------------------------------------------------------

    def _group(self, name: str) -> dict:
        return self.terminology.get(name) or {}

    def verbs(self, group: str) -> List[str]:
        return [str(v) for v in (self._group(group).get("verbs") or [])]

    @property
    def binding_verb(self) -> str:
        verbs = self.verbs("binding")
        return verbs[0] if verbs else "shall"

    @property
    def binding_label(self) -> str:
        return self._group("binding").get("label") or "requirement"

    def count_binding(self, text: str) -> int:
        return sum(_count_term(text, verb) for verb in self.verbs("binding"))

    def first_nonbinding(self, text: str):
        """Return ``(verb, label)`` for the first non-binding modal in priority order."""
        for group in _NONBINDING_ORDER:
            label = self._group(group).get("label") or group.replace("_", " ")
            for verb in self.verbs(group):
                if _has_term(text, verb):
                    return verb, label
        return None

    def mixed_modals(self, text: str) -> List[str]:
        """Non-binding modals that blur a statement which already has a binding verb.

        ``can`` is skipped: it shows up inside ``shall be capable`` and is not,
        by itself, a second obligation.
        """
        found = []
        for group in _NONBINDING_ORDER:
            for verb in self.verbs(group):
                if verb.lower() == "can":
                    continue
                if _has_term(text, verb) and verb not in found:
                    found.append(verb)
        return found

    def leading_modals(self) -> List[str]:
        verbs = self.verbs("binding") + self.verbs("discouraged") + self.verbs("goal")
        return [v for v in verbs if " " not in v]

    def extra_terms(self, key: str) -> List[str]:
        return list(self.vocabulary.get(key) or [])

    def max_words(self) -> int:
        return int(self.parameters.get("max_words", 45))

    # -- verification ------------------------------------------------------

    def score_methods(self, text: str):
        low = text.lower()
        out = {}
        for name, cues in self._cues:
            score = 0
            why = []
            for pattern, weight, desc in cues:
                if pattern.search(low):
                    score += weight
                    why.append(desc)
            out[name] = (score, why)
        return out

    @property
    def default_method(self) -> str:
        return self.verification.get("default_method") or self.methods[0]["name"]

    def method_names(self) -> List[str]:
        return [m["name"] for m in self.methods]

    # -- identifiers -------------------------------------------------------

    def identifier_violation(self, req_id: str):
        """Return ``(severity, message)`` when a non-generated id breaks the convention."""
        enforce = (self.identifiers.get("enforce") or "off").lower()
        if enforce in {"", "off", "none"} or self._id_pattern is None:
            return None
        if self._id_pattern.match(req_id or ""):
            return None
        severity = "Medium" if enforce == "strict" else "Low"
        return severity

    def enabled_rule_ids(self, all_ids: List[str]) -> List[str]:
        known = list(all_ids)
        if self.rule_shared == "all":
            chosen = known
        else:
            unknown = [rid for rid in self.rule_shared if rid not in known]
            if unknown:
                raise ProfileError(f"Profile '{self.id}' names unknown rules: {', '.join(unknown)}.")
            chosen = [rid for rid in known if rid in set(self.rule_shared)]
        return [rid for rid in chosen if rid not in self.rule_disabled]

    def to_public_dict(self) -> dict:
        """JSON-safe description. Cue patterns are omitted on purpose."""
        return {
            "id": self.id,
            "name": self.name,
            "short_name": self.short_name,
            "audience": self.audience,
            "summary": self.summary,
            "default": self.is_default,
            "references": self.references,
            "terminology": {
                "note": (self.terminology.get("note") or "").strip(),
                **{g: {"verbs": self.verbs(g), "label": self._group(g).get("label") or ""}
                   for g in MODAL_GROUPS if self.verbs(g)},
            },
            "verification_methods": [
                {"name": m["name"], "short": m["short"], "legend": m.get("legend") or m["name"]}
                for m in self.methods
            ],
            "default_method": self.default_method,
            "verification_note": (self.verification.get("note") or "").strip(),
            "level_hint": self.verification.get("level_hint") or "",
            "stage_hint": self.verification.get("stage_hint") or "",
            "milestones": self.milestones,
            "document_types": self.document_types,
            "identifiers": {
                "description": (self.identifiers.get("description") or "").strip(),
                "example": self.identifiers.get("example") or "",
                "pattern": self.identifiers.get("pattern") or "",
                "enforce": self.identifiers.get("enforce") or "off",
            },
            "extra_rules": [
                {"id": r["id"], "name": r["name"], "severity": r["severity"],
                 "summary": (r.get("summary") or "").strip()}
                for r in self.extra_rules
            ],
            "parameters": {"max_words": self.max_words()},
        }


class Registry:
    def __init__(self, profiles: Dict[str, Profile]):
        defaults = [p for p in profiles.values() if p.is_default]
        if len(defaults) != 1:
            names = ", ".join(sorted(p.id for p in defaults)) or "none"
            raise ProfileError(f"Exactly one profile must set default: true (found: {names}).")
        self.by_id = profiles
        self.default = defaults[0]

    def get(self, profile_id: Optional[str]) -> Profile:
        if profile_id is None or str(profile_id).strip() == "":
            return self.default
        key = str(profile_id).strip().lower()
        if key not in self.by_id:
            known = ", ".join(self.ids())
            raise ProfileError(f"Unknown standards profile '{profile_id}'. Known profiles: {known}.")
        return self.by_id[key]

    def ids(self) -> List[str]:
        return [p.id for p in self._ordered()]

    def public_list(self) -> List[dict]:
        return [p.to_public_dict() for p in self._ordered()]

    def _ordered(self) -> List[Profile]:
        return sorted(self.by_id.values(), key=lambda p: (p.order, p.id))


_CACHE: Optional[Registry] = None
_CATALOG: Optional[dict] = None


def get_registry() -> Registry:
    global _CACHE
    if _CACHE is None:
        _CACHE = load_registry(profiles_root())
    return _CACHE


def get_rule_catalog() -> dict:
    global _CATALOG
    if _CATALOG is None:
        path = profiles_root() / "_rule_catalog.yaml"
        _CATALOG = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _CATALOG


def resolve_profile(profile=None) -> Profile:
    if isinstance(profile, Profile):
        return profile
    return get_registry().get(profile)


def reset_caches() -> None:
    """Test hook. Production loads once per process."""
    global _CACHE, _CATALOG
    _CACHE = None
    _CATALOG = None


def load_registry(root: Path) -> Registry:
    root = Path(root)
    defaults_path = root / "_defaults.yaml"
    defaults = yaml.safe_load(defaults_path.read_text(encoding="utf-8")) if defaults_path.is_file() else {}
    defaults = defaults or {}
    method_sets = _load_method_sets(root / "method_sets")
    profiles: Dict[str, Profile] = {}
    for path in sorted(root.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        raw = _load_yaml(path)
        if not isinstance(raw, dict) or "id" not in raw:
            raise ProfileError(f"{path.name} is not a profile (missing id).")
        merged = _merge_profile(defaults, raw, path.name)
        methods = _methods_for(merged, method_sets, path.name)
        profile = Profile(merged, methods)
        _validate(profile, path.name)
        if profile.id in profiles:
            raise ProfileError(f"Duplicate profile id '{profile.id}'.")
        profiles[profile.id] = profile
    if not profiles:
        raise ProfileError(f"No profiles found in {root}.")
    return Registry(profiles)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _load_yaml(path: Path):
    if not path.is_file():
        raise ProfileError(f"Missing {path}.")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def _load_method_sets(directory: Path) -> Dict[str, List[dict]]:
    sets: Dict[str, List[dict]] = {}
    if not directory.is_dir():
        return sets
    for path in sorted(directory.glob("*.yaml")):
        raw = _load_yaml(path)
        if not isinstance(raw, dict) or "id" not in raw or "methods" not in raw:
            raise ProfileError(f"{path.name} is not a method set.")
        sets[str(raw["id"])] = raw["methods"]
    return sets


def _merge_profile(defaults: dict, raw: dict, filename: str) -> dict:
    merged = dict(raw)
    params = dict(defaults.get("parameters") or {})
    params.update(raw.get("parameters") or {})
    merged["parameters"] = params
    rule_set = dict(defaults.get("rule_set") or {})
    rule_set.update(raw.get("rule_set") or {})
    merged["rule_set"] = rule_set
    terminology = dict(defaults.get("terminology") or {})
    terminology.update(raw.get("terminology") or {})
    merged["terminology"] = terminology
    identifiers = dict(defaults.get("identifiers") or {})
    identifiers.update(raw.get("identifiers") or {})
    merged["identifiers"] = identifiers
    verification = dict(defaults.get("verification") or {})
    verification.update(raw.get("verification") or {})
    merged["verification"] = verification
    if "summary" in merged and isinstance(merged["summary"], str):
        merged["summary"] = merged["summary"].strip()
    if filename.removesuffix(".yaml") != str(merged.get("id")):
        raise ProfileError(
            f"{filename} declares id '{merged.get('id')}'. The file name and the id must match."
        )
    return merged


def _methods_for(data: dict, method_sets: Dict[str, List[dict]], filename: str) -> List[dict]:
    verification = data.get("verification") or {}
    if verification.get("methods"):
        methods = [dict(m) for m in verification["methods"]]
    else:
        set_id = verification.get("method_set")
        if not set_id:
            raise ProfileError(f"{filename} needs verification.method_set or verification.methods.")
        if set_id not in method_sets:
            known = ", ".join(sorted(method_sets)) or "none"
            raise ProfileError(f"{filename} references unknown method set '{set_id}'. Known: {known}.")
        methods = [dict(m) for m in method_sets[set_id]]
    order = verification.get("method_order")
    if order:
        by_name = {m["name"]: m for m in methods}
        missing = [name for name in order if name not in by_name]
        if missing or len(order) != len(methods):
            raise ProfileError(f"{filename} method_order must list each method once.")
        methods = [by_name[name] for name in order]
    return methods


def _validate(profile: Profile, filename: str) -> None:
    if not profile.verbs("binding"):
        raise ProfileError(f"{filename} needs at least one binding verb.")
    if not profile.methods:
        raise ProfileError(f"{filename} has no verification methods.")
    names = [m["name"] for m in profile.methods]
    if len(names) != len(set(names)):
        raise ProfileError(f"{filename} repeats a verification method name.")
    for method in profile.methods:
        if not method.get("short"):
            raise ProfileError(f"{filename} method '{method.get('name')}' needs a short letter.")
        for cue in method.get("cues") or []:
            for key in ("pattern", "weight", "cue"):
                if key not in cue:
                    raise ProfileError(f"{filename} cue on '{method['name']}' is missing {key}.")
    if profile.default_method not in names:
        raise ProfileError(
            f"{filename} default_method '{profile.default_method}' is not one of: {', '.join(names)}."
        )
    if not profile.references:
        raise ProfileError(f"{filename} needs at least one reference (number and title only).")
    for ref in profile.references:
        if not ref.get("number") or not ref.get("title"):
            raise ProfileError(f"{filename} references need a number and a title.")
    if not (profile.terminology.get("note") or "").strip():
        raise ProfileError(f"{filename} needs terminology.note written in your own words.")
    if not profile.milestones or not profile.document_types:
        raise ProfileError(f"{filename} needs milestones and document_types.")
    for rule in profile.extra_rules:
        for key in ("id", "name", "severity", "message", "suggestion", "when"):
            if not rule.get(key):
                raise ProfileError(f"{filename} extra rule is missing {key}.")
        if rule["severity"] not in SEVERITIES:
            raise ProfileError(f"{filename} extra rule '{rule['id']}' has an unknown severity.")
        if rule["id"].startswith(("RQ-", "DOC-")):
            raise ProfileError(f"{filename} extra rule id '{rule['id']}' collides with a shared rule.")
        _compile_condition(rule["when"], f"{filename} rule {rule['id']}")
        if rule.get("unless"):
            _compile_condition(rule["unless"], f"{filename} rule {rule['id']}")
    enforce = (profile.identifiers.get("enforce") or "off").lower()
    if enforce not in {"off", "none", "advisory", "strict"}:
        raise ProfileError(f"{filename} identifiers.enforce must be off, advisory, or strict.")
    if enforce in {"advisory", "strict"} and not profile.identifiers.get("pattern"):
        raise ProfileError(f"{filename} enforces an identifier convention but has no pattern.")
    if not profile.identifiers.get("example"):
        raise ProfileError(f"{filename} needs identifiers.example.")


def _compile_condition(cond: dict, where: str) -> None:
    if not isinstance(cond, dict):
        raise ProfileError(f"{where} condition must be a mapping.")
    if not any(cond.get(k) for k in ("any_terms", "all_terms", "any_regex")):
        raise ProfileError(f"{where} condition needs any_terms, all_terms, or any_regex.")
    for pattern in cond.get("any_regex") or []:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ProfileError(f"{where} has a bad regular expression: {exc}") from exc


def _has_term(text: str, term: str) -> bool:
    return _count_term(text, term) > 0


def _count_term(text: str, term: str) -> int:
    return len(re.findall(r"(?<![\w-])" + re.escape(term) + r"(?![\w-])", text, flags=re.I))
