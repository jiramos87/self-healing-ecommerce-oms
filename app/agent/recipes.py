"""Typed fix recipes and the deterministic pre-PR gate."""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from typing import Any

from app.agent.schemas import PhoneFormatParams, UnknownRegionParams, validate_recipe_params

ALLOWLIST = frozenset(
    {
        "app/data/regions.json",
        "app/data/phone_rules.json",
    }
)

LINE_BUDGET = 1

REGIONS_PATH = "app/data/regions.json"
PHONE_RULES_PATH = "app/data/phone_rules.json"

RECIPE_PATHS: dict[str, str] = {
    "unknown_region": REGIONS_PATH,
    "phone_format": PHONE_RULES_PATH,
}


@dataclass(frozen=True)
class RecipeChange:
    path: str
    old_content: str
    new_content: str


@dataclass(frozen=True)
class GateResult:
    ok: bool
    violated_rule: str | None = None


def count_line_edits(old_content: str, new_content: str) -> tuple[int, int]:
    """Return (additions, deletions) exactly as a git-style diff counts them.

    A modified line counts as one deletion plus one addition, so the gate
    scores the same numbers GitHub will render on the PR.
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    additions = 0
    deletions = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, old_lines, new_lines
    ).get_opcodes():
        if tag in {"replace", "delete"}:
            deletions += i2 - i1
        if tag in {"replace", "insert"}:
            additions += j2 - j1
    return additions, deletions


def apply_unknown_region(old_content: str, params: UnknownRegionParams) -> str:
    """Insert one mapping line right after the opening brace.

    Top-insertion leaves every existing line untouched (the trailing comma
    rides the new line), so the PR diff is literally one added line and zero
    deletions. Key order is irrelevant to the lookup.
    """
    data = json.loads(old_content)
    if not isinstance(data, dict):
        raise ValueError("regions.json root must be an object")
    if params.province_code in data:
        raise ValueError(f"province_code already present: {params.province_code}")

    lines = old_content.splitlines(keepends=True)
    open_idx = next((i for i, line in enumerate(lines) if line.strip() == "{"), None)
    if open_idx is None:
        raise ValueError("regions.json missing opening brace")

    code_json = json.dumps(params.province_code, ensure_ascii=False)
    name_json = json.dumps(params.province, ensure_ascii=False)
    suffix = "," if data else ""
    lines.insert(open_idx + 1, f"  {code_json}: {name_json}{suffix}\n")
    return "".join(lines)


def apply_phone_format(old_content: str, params: PhoneFormatParams) -> str:
    """Insert one single-line rule object at the top of the rules array.

    Same top-insertion rationale as regions: one added line, zero touched
    lines. Rule order does not change matching results (first-match returns
    the candidate itself, and a novel pattern cannot shadow existing rules).
    """
    data = json.loads(old_content)
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise ValueError("phone_rules.json must have a rules array")
    if any(
        isinstance(r, dict) and r.get("name") == params.name for r in data["rules"]
    ):
        raise ValueError(f"rule name already present: {params.name}")

    lines = old_content.splitlines(keepends=True)
    open_idx = next(
        (
            i
            for i, line in enumerate(lines)
            if '"rules"' in line and line.rstrip().endswith("[")
        ),
        None,
    )
    if open_idx is None:
        raise ValueError("phone_rules.json missing rules array open")

    rule_obj = {
        "name": params.name,
        "pattern": params.pattern,
        "description": params.description,
    }
    suffix = "," if data["rules"] else ""
    new_line = "    " + json.dumps(rule_obj, ensure_ascii=False) + suffix + "\n"
    lines.insert(open_idx + 1, new_line)
    return "".join(lines)


def apply_recipe(
    class_: str,
    params: dict[str, Any],
    *,
    file_contents: dict[str, str],
) -> RecipeChange:
    validated = validate_recipe_params(class_, params)
    if class_ == "unknown_region":
        path = REGIONS_PATH
        assert isinstance(validated, UnknownRegionParams)
        old = file_contents[path]
        new = apply_unknown_region(old, validated)
        return RecipeChange(path=path, old_content=old, new_content=new)
    if class_ == "phone_format":
        path = PHONE_RULES_PATH
        assert isinstance(validated, PhoneFormatParams)
        old = file_contents[path]
        new = apply_phone_format(old, validated)
        return RecipeChange(path=path, old_content=old, new_content=new)
    raise ValueError(f"no recipe for class {class_}")


def gate_change(
    change: RecipeChange,
    *,
    class_: str,
    params: dict[str, Any],
) -> GateResult:
    """Hard gate before opening a PR. Names the first violated rule."""
    if class_ not in RECIPE_PATHS:
        return GateResult(ok=False, violated_rule="unknown_recipe")

    if change.path not in ALLOWLIST:
        return GateResult(ok=False, violated_rule="allowlist")

    additions, deletions = count_line_edits(change.old_content, change.new_content)
    if deletions > 0:
        return GateResult(ok=False, violated_rule="no_deletions")
    if additions > LINE_BUDGET or additions < 1:
        return GateResult(ok=False, violated_rule="line_budget")

    try:
        parsed = json.loads(change.new_content)
    except json.JSONDecodeError:
        return GateResult(ok=False, violated_rule="parses")

    validated = validate_recipe_params(class_, params)
    if class_ == "unknown_region":
        assert isinstance(validated, UnknownRegionParams)
        if not isinstance(parsed, dict):
            return GateResult(ok=False, violated_rule="parses")
        if parsed.get(validated.province_code) != validated.province:
            return GateResult(ok=False, violated_rule="key_resolves")
    elif class_ == "phone_format":
        assert isinstance(validated, PhoneFormatParams)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("rules"), list):
            return GateResult(ok=False, violated_rule="parses")
        rules = parsed["rules"]
        match = next(
            (
                r
                for r in rules
                if isinstance(r, dict)
                and r.get("name") == validated.name
                and r.get("pattern") == validated.pattern
            ),
            None,
        )
        if match is None:
            return GateResult(ok=False, violated_rule="key_resolves")
        try:
            re.compile(validated.pattern)
        except re.error:
            return GateResult(ok=False, violated_rule="key_resolves")

    return GateResult(ok=True)
