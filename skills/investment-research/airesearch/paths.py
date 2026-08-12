#!/usr/bin/env python
"""Where this project's files live.

Every module resolves through here so there is one answer, and so that answer
survives being installed rather than cloned. Two modules each deriving a
repo-relative path independently is how one of them quietly keeps working while
the other writes into site-packages.

Resolution order, for both the database and the config file:
  1. the matching environment variable, if set — an explicit override always wins
  2. the path inside the source checkout, when running from one
  3. a per-user directory otherwise

Step 3 matters because a non-editable `pip install .` puts these modules inside
site-packages, where a repo-relative path would resolve to
site-packages/db/research.db: unwritable on a system Python, and wiped on the
next upgrade if it is writable.
"""

import os
from pathlib import Path

DB_ENV_VAR = "AI_RESEARCH_DB"
PROFILE_ENV_VAR = "AI_RESEARCH_PROFILE"

_USER_DIR = Path.home() / ".ai-investment-research"

# paths.py lives at <root>/skills/investment-research/airesearch/paths.py
_CHECKOUT_ROOT = Path(__file__).resolve().parents[3]


def _is_source_checkout(root: Path) -> bool:
    """A checkout has the project file next to the package; an install does not."""
    return (root / "pyproject.toml").is_file()


def _resolve(env_var: str, relative: Path) -> Path:
    override = os.environ.get(env_var)
    if override:
        return Path(override).expanduser()
    if _is_source_checkout(_CHECKOUT_ROOT):
        return _CHECKOUT_ROOT / relative
    return _USER_DIR / relative.name


def default_db_path() -> Path:
    return _resolve(DB_ENV_VAR, Path("db") / "research.db")


def default_profile_path() -> Path:
    return _resolve(PROFILE_ENV_VAR, Path("config") / "research-profile.json")
