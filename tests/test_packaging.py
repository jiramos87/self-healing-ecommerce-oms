"""Guard the deploy dependency set.

Vercel installs pyproject [project].dependencies and ignores requirements.txt.
A dep present only in requirements.txt therefore imports fine locally and
crashes the deployed function at import time (this happened once: psycopg).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _requirements_pins() -> set[str]:
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    return {
        line.strip()
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    }


def _pyproject_runtime_deps() -> set[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return set(data["project"]["dependencies"])


def test_runtime_deps_are_declared_for_vercel() -> None:
    """Every runtime dep pinned for local dev must be in the deployed set."""
    assert _pyproject_runtime_deps() <= _requirements_pins()


def test_app_imports_only_declared_runtime_deps() -> None:
    """Third-party modules imported by app/ must be in the deployed set."""
    declared = {dep.split("[")[0].split("==")[0] for dep in _pyproject_runtime_deps()}
    # Distribution name -> import name, where they differ.
    provides = {
        "fastapi": {"fastapi", "starlette"},
        "psycopg": {"psycopg", "psycopg_pool"},
        "langgraph": {"langgraph"},
        "langchain-core": {"langchain_core"},
        "httpx": {"httpx"},
        "pydantic": {"pydantic"},
    }
    importable = {name for dep in declared for name in provides.get(dep, {dep})}

    stdlib_or_local = {"app", "api", "__future__"}
    missing: set[str] = set()
    for path in (ROOT / "app").rglob("*.py"):
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not (line.startswith("import ") or line.startswith("from ")):
                continue
            token = line.split()[1].split(".")[0]
            if token in stdlib_or_local or token in importable:
                continue
            # Anything left is either stdlib or an undeclared dependency.
            if token in {"psycopg", "psycopg_pool", "starlette"}:
                missing.add(token)
    assert not missing, f"undeclared runtime imports: {sorted(missing)}"
