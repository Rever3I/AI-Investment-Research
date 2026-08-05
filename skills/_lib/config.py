#!/usr/bin/env python
"""User configuration for the research pipeline.

JSON rather than YAML: this project ships with no third-party dependencies, and
YAML has no stdlib parser (tomllib would need 3.11, this targets 3.10).

Every setting has a working default, so a missing or partial config file is a
normal state rather than an error. A user who never opens the file still gets a
functioning pipeline.
"""

import json
import logging
import os
from pathlib import Path

_log = logging.getLogger(__name__)

_ENV_VAR = "AI_RESEARCH_PROFILE"

# config.py lives at <root>/skills/_lib/config.py
_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE_PATH = _ROOT / "config" / "research-profile.json"

DEFAULTS = {
    # Language for research output the user reads: thesis prose, valuation
    # commentary, verdicts. Any language tag the model understands works; there
    # is no whitelist, for the same reason there is no market whitelist.
    # This does not change the code's own log or error messages, which stay
    # English so a traceback is searchable by anyone.
    "output_language": "en",
    # Position sizing, consumed by research-portfolio.
    "sizing_method": "half_kelly",
    # Whether the optional dissent layer participates.
    "debate_enabled": False,
}


def profile_path(path=None) -> Path:
    if path:
        return Path(path).expanduser()
    override = os.environ.get(_ENV_VAR)
    return Path(override).expanduser() if override else DEFAULT_PROFILE_PATH


def load_profile(path=None) -> dict:
    """Return the user's settings, with defaults filled in for anything absent.

    A malformed file warns and falls back to defaults rather than raising: a
    typo in an optional config should not take the whole pipeline down.
    """
    resolved = profile_path(path)
    profile = dict(DEFAULTS)
    if not resolved.is_file():
        return profile
    try:
        loaded = json.loads(resolved.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _log.warning("Could not read the research profile at %s, using defaults",
                     resolved, exc_info=True)
        return profile
    if not isinstance(loaded, dict):
        _log.warning("The research profile at %s is not a JSON object, using defaults",
                     resolved)
        return profile
    profile.update(loaded)
    return profile


def output_language(path=None) -> str:
    """The language research output should be written in."""
    value = load_profile(path).get("output_language") or DEFAULTS["output_language"]
    return str(value).strip()
