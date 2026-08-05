#!/usr/bin/env python
"""User configuration for the research pipeline.

JSON rather than YAML: this project ships with no third-party dependencies, and
YAML has no stdlib parser (tomllib would need 3.11, this targets 3.10).

Every setting has a working default, so a missing, partial, or damaged config
file is a normal state rather than an error. A user who never opens the file
still gets a functioning pipeline, and one who corrupts it gets a warning plus
the defaults rather than a stack trace.
"""

import copy
import json
import logging
from pathlib import Path
from types import MappingProxyType

from .paths import default_profile_path

_log = logging.getLogger(__name__)

# Read with utf-8-sig, not utf-8: it decodes plain UTF-8 identically but also
# strips a byte-order mark. Several CJK editors write a BOM by default, and a
# BOM'd file otherwise fails to parse and silently reverts the user's language.
_ENCODING = "utf-8-sig"

_DEFAULTS = {
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

# Read-only view, so an import cannot poison every later caller in the process.
DEFAULTS = MappingProxyType(_DEFAULTS)


def profile_path(path=None) -> Path:
    return Path(path).expanduser() if path else default_profile_path()


def _coerce(loaded: dict, source: Path) -> dict:
    """Keep the settings that are recognised and correctly typed, warn about the rest.

    A wrong type is worse than a missing value here: `"debate_enabled": "false"`
    is a truthy string, so a user who typed it would silently enable the layer
    they meant to turn off.
    """
    clean = {}
    for key, value in loaded.items():
        if key not in _DEFAULTS:
            _log.warning("Unknown setting %r in %s, ignoring it", key, source)
            continue
        expected = type(_DEFAULTS[key])
        # bool is a subclass of int, so check it first and exactly.
        if expected is bool:
            ok = isinstance(value, bool)
        else:
            ok = isinstance(value, expected) and not isinstance(value, bool)
        if not ok:
            _log.warning(
                "Setting %r in %s should be %s, got %r, using the default instead",
                key, source, expected.__name__, value,
            )
            continue
        clean[key] = value
    return clean


def load_profile(path=None) -> dict:
    """Return the user's settings, with defaults filled in for anything absent
    or unusable."""
    resolved = profile_path(path)
    profile = copy.deepcopy(_DEFAULTS)
    if not resolved.is_file():
        return profile
    try:
        raw = resolved.read_text(encoding=_ENCODING)
    except (OSError, UnicodeDecodeError) as exc:
        # A zh-CN Windows user editing this in Notepad can save it as GBK.
        # That must degrade to defaults, not take down the pipeline.
        _log.warning("Could not read the research profile at %s (%s), using defaults",
                     resolved, exc)
        return profile
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        _log.warning("The research profile at %s is not valid JSON (%s), using defaults",
                     resolved, exc)
        return profile
    if not isinstance(loaded, dict):
        _log.warning("The research profile at %s is not a JSON object, using defaults",
                     resolved)
        return profile
    profile.update(_coerce(loaded, resolved))
    return profile


def output_language(path=None) -> str:
    """The language research output should be written in."""
    value = str(load_profile(path).get("output_language") or "").strip()
    return value or _DEFAULTS["output_language"]
