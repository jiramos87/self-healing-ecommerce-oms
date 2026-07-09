"""Recipe apply + pre-PR gate tests."""

from __future__ import annotations

import json
from pathlib import Path

from app.agent.recipes import (
    ALLOWLIST,
    PHONE_RULES_PATH,
    REGIONS_PATH,
    RecipeChange,
    apply_recipe,
    count_line_edits,
    gate_change,
)

ROOT = Path(__file__).resolve().parents[1]


def _live_contents() -> dict[str, str]:
    return {
        REGIONS_PATH: (ROOT / REGIONS_PATH).read_text(encoding="utf-8"),
        PHONE_RULES_PATH: (ROOT / PHONE_RULES_PATH).read_text(encoding="utf-8"),
    }


def test_unknown_region_one_line_addition_passes_gate() -> None:
    contents = _live_contents()
    params = {"province_code": "QQ", "province": "Quebrada Quimera"}
    change = apply_recipe("unknown_region", params, file_contents=contents)
    assert change.path == REGIONS_PATH
    additions, deletions = count_line_edits(change.old_content, change.new_content)
    assert additions == 1
    assert deletions == 0
    gate = gate_change(change, class_="unknown_region", params=params)
    assert gate.ok is True
    parsed = json.loads(change.new_content)
    assert parsed["QQ"] == "Quebrada Quimera"


def test_phone_format_one_line_addition_passes_gate() -> None:
    contents = _live_contents()
    params = {
        "name": "demo_odd",
        "pattern": "^00-DEMO-\\d+$",
        "description": "demo odd phone",
    }
    change = apply_recipe("phone_format", params, file_contents=contents)
    assert change.path == PHONE_RULES_PATH
    additions, deletions = count_line_edits(change.old_content, change.new_content)
    assert additions == 1
    assert deletions == 0
    gate = gate_change(change, class_="phone_format", params=params)
    assert gate.ok is True


def test_gate_allowlist_violation() -> None:
    change = RecipeChange(
        path="app/main.py",
        old_content="a\n",
        new_content="a\nb\n",
    )
    gate = gate_change(
        change,
        class_="unknown_region",
        params={"province_code": "ZZ", "province": "Zed"},
    )
    assert gate.ok is False
    assert gate.violated_rule == "allowlist"


def test_gate_line_budget_violation() -> None:
    old = '{\n  "RM": "Santiago"\n}\n'
    # Two top-inserted mapping lines exceed the one-line budget.
    new = '{\n  "AA": "One",\n  "BB": "Two",\n  "RM": "Santiago"\n}\n'
    change = RecipeChange(path=REGIONS_PATH, old_content=old, new_content=new)
    additions, deletions = count_line_edits(old, new)
    assert additions == 2
    assert deletions == 0
    assert json.loads(new)["AA"] == "One"
    gate = gate_change(
        change,
        class_="unknown_region",
        params={"province_code": "AA", "province": "One"},
    )
    assert gate.ok is False
    assert gate.violated_rule == "line_budget"


def test_gate_counts_modified_lines_like_git() -> None:
    # A trailing-comma rewrite of an existing line is one deletion plus one
    # addition on the real PR diff; the gate must reject it, not discount it.
    old = '{\n  "RM": "Santiago"\n}\n'
    new = '{\n  "RM": "Santiago",\n  "AA": "One"\n}\n'
    additions, deletions = count_line_edits(old, new)
    assert additions == 2
    assert deletions == 1
    gate = gate_change(
        RecipeChange(path=REGIONS_PATH, old_content=old, new_content=new),
        class_="unknown_region",
        params={"province_code": "AA", "province": "One"},
    )
    assert gate.ok is False
    assert gate.violated_rule == "no_deletions"


def test_gate_unknown_class_names_unknown_recipe() -> None:
    change = RecipeChange(
        path=REGIONS_PATH,
        old_content="{\n}\n",
        new_content='{\n  "A": "B"\n}\n',
    )
    gate = gate_change(change, class_="mystery", params={})
    assert gate.ok is False
    assert gate.violated_rule == "unknown_recipe"


def test_gate_no_deletions_violation() -> None:
    old = '{\n  "RM": "Región Metropolitana de Santiago",\n  "VS": "Valparaíso"\n}\n'
    new = '{\n  "RM": "Región Metropolitana de Santiago",\n  "QQ": "Quebrada"\n}\n'
    change = RecipeChange(path=REGIONS_PATH, old_content=old, new_content=new)
    _additions, deletions = count_line_edits(old, new)
    assert deletions >= 1
    gate = gate_change(
        change,
        class_="unknown_region",
        params={"province_code": "QQ", "province": "Quebrada"},
    )
    assert gate.ok is False
    assert gate.violated_rule == "no_deletions"


def test_gate_parses_violation() -> None:
    # One added line, zero deletions, but content is not valid JSON.
    change = RecipeChange(
        path=REGIONS_PATH,
        old_content="{\n}\n",
        new_content="{\n  not-json\n}\n",
    )
    additions, deletions = count_line_edits(change.old_content, change.new_content)
    assert additions == 1
    assert deletions == 0
    gate = gate_change(
        change,
        class_="unknown_region",
        params={"province_code": "QQ", "province": "Q"},
    )
    assert gate.ok is False
    assert gate.violated_rule == "parses"


def test_gate_key_resolves_violation() -> None:
    contents = _live_contents()
    params = {"province_code": "QQ", "province": "Quebrada Quimera"}
    change = apply_recipe("unknown_region", params, file_contents=contents)
    # Params claim a different value than what was written.
    gate = gate_change(
        change,
        class_="unknown_region",
        params={"province_code": "QQ", "province": "Wrong Name"},
    )
    assert gate.ok is False
    assert gate.violated_rule == "key_resolves"


def test_allowlist_matches_seams() -> None:
    assert ALLOWLIST == frozenset({REGIONS_PATH, PHONE_RULES_PATH})
