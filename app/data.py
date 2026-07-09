"""Single cached loader for the JSON data files in app/data/.

Caching per warm instance is correct here: agent fix PRs change these files
in the GitHub repo, and they take effect on redeploy (fresh instances).
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"


@cache
def load_data_file(name: str) -> Any:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))
