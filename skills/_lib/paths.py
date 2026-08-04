#!/usr/bin/env python
"""Where the research database lives.

Both storage layers resolve through here so there is exactly one answer, and so
that answer survives being installed rather than cloned.

Resolution order:
  1. $AI_RESEARCH_DB, if set — an explicit override always wins
  2. <repo>/db/research.db, when running from a source checkout
  3. ~/.ai-investment-research/research.db otherwise

Step 3 matters because a non-editable `pip install .` puts this file inside
site-packages, where the repo-relative path would resolve to
site-packages/db/research.db: unwritable on a system Python, and wiped on the
next upgrade if it is writable.
"""

import os
from pathlib import Path

_ENV_VAR = "AI_RESEARCH_DB"
_USER_FALLBACK = Path.home() / ".ai-investment-research" / "research.db"

# paths.py lives at <root>/skills/_lib/paths.py
_CHECKOUT_ROOT = Path(__file__).resolve().parents[2]


def _is_source_checkout(root: Path) -> bool:
    """A checkout has the project file next to the package; an install does not."""
    return (root / "pyproject.toml").is_file()


def default_db_path() -> Path:
    override = os.environ.get(_ENV_VAR)
    if override:
        return Path(override).expanduser()
    if _is_source_checkout(_CHECKOUT_ROOT):
        return _CHECKOUT_ROOT / "db" / "research.db"
    return _USER_FALLBACK
