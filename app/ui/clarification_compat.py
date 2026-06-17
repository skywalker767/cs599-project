"""Compatibility helpers for clarification multi-select UI."""

from __future__ import annotations


def build_incompat_map(question: dict) -> dict[str, set[str]]:
    """Return value -> set of incompatible option values for a question."""
    options = question.get("options", [])
    values = [o["value"] for o in options]
    qtype = question.get("question_type", "single_choice")

    result: dict[str, set[str]] = {v: set() for v in values}
    if qtype == "single_choice":
        for v in values:
            result[v] = set(values) - {v}
        return result

    for opt in options:
        val = opt["value"]
        explicit = set(opt.get("incompatible_with") or [])
        result[val] = explicit & set(values)
    return result


def is_blocked(value: str, selected: list[str], incompat: dict[str, set[str]]) -> bool:
    """True if value conflicts with any currently selected option."""
    if value in selected:
        return False
    for sel in selected:
        if value in incompat.get(sel, set()) or sel in incompat.get(value, set()):
            return True
    return False


def sanitize_selection(
    selected: list[str],
    incompat: dict[str, set[str]],
    *,
    exclusive: bool,
) -> list[str]:
    """Remove conflicts; for exclusive questions keep only the last pick."""
    if not selected:
        return []

    if exclusive:
        return [selected[-1]]

    cleaned: list[str] = []
    for val in selected:
        if any(
            val in incompat.get(prev, set()) or prev in incompat.get(val, set()) for prev in cleaned
        ):
            continue
        cleaned.append(val)
    return cleaned


def selection_to_storage(values: list[str]) -> str:
    return ";".join(values)


def storage_to_selection(raw: str | list[str] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(v) for v in raw if str(v)]
    text = str(raw).strip()
    if not text:
        return []
    if ";" in text:
        return [v for v in text.split(";") if v]
    return [text]
