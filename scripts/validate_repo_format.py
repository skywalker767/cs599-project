"""Fail CI if critical text files collapse to a single line (common copy/paste corruption)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHECK_PATHS = [
    ROOT / "requirements.txt",
    ROOT / "Dockerfile",
    ROOT / ".env.example",
    ROOT / "app" / "main.py",
    ROOT / "app" / "config.py",
    ROOT / "app" / "services" / "generation_service.py",
    ROOT / "app" / "models" / "schemas.py",
    ROOT / "app" / "tools" / "benchmark.py",
    ROOT / "benchmark.py",
]

SKIP_DIRS = {".venv", "storage", "__pycache__", ".git"}


def _check_file(path: Path) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        return errors
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if path.suffix == ".py" and len(lines) <= 2 and len(text) > 300:
        errors.append(f"{path}: Python file looks like a single compressed line ({len(lines)} lines)")
    if path.name == "requirements.txt":
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if " " in stripped and ">=" in stripped and stripped.count(">=") > 1:
                errors.append(f"{path}:{i}: multiple packages on one line")
    if path.name == "Dockerfile" and "FROM" in text and "WORKDIR" in text:
        if text.count("\n") < 3:
            errors.append(f"{path}: Dockerfile appears to be one line")
    if path.name == ".env.example":
        if text.lstrip().startswith("#") and "IMAGE_PROVIDER=" not in text:
            errors.append(f"{path}: env vars may be commented out entirely")
    return errors


def main() -> int:
    errors: list[str] = []
    for path in CHECK_PATHS:
        errors.extend(_check_file(path))

    for py in (ROOT / "app").rglob("*.py"):
        if any(part in SKIP_DIRS for part in py.parts):
            continue
        errors.extend(_check_file(py))

    if errors:
        print("Repository format validation FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("Repository format validation OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
