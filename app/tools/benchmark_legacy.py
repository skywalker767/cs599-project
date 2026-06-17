"""Legacy JSON benchmark case loader for tests."""

from __future__ import annotations

import json

from app.config import PROJECT_ROOT

EXAMPLES_DIR = PROJECT_ROOT / "examples"


def load_legacy_cases(rel_paths: list[str]) -> list[dict]:
    cases: list[dict] = []
    for rel_path in rel_paths:
        path = EXAMPLES_DIR / rel_path
        case = json.loads(path.read_text(encoding="utf-8"))
        case["id"] = case.get("id", path.stem)
        case["input"] = case.get("user_input", case.get("input", ""))
        case["expected_aspect_ratio"] = case.get("aspect_ratio", "1:1")
        case["key_requirements"] = case.get("key_requirements", [])
        cases.append(case)
    return cases
