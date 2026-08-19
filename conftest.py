"""Make the skill's library importable for the test suite.

The library lives inside the skill directory so that directory is
self-contained: a marketplace that copies `skills/agentic-stock-researcher/` gets a
working install, which was not true when the code sat in a sibling folder.
"""

import sys
from pathlib import Path

_SKILL = Path(__file__).resolve().parent / "skills" / "agentic-stock-researcher"
if str(_SKILL) not in sys.path:
    sys.path.insert(0, str(_SKILL))
