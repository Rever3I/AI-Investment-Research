"""Make the repo root importable for the test suite.

Lives at the repo root rather than in tests/ so pytest also treats this
directory as its rootdir. Without that anchor, invoking pytest with an absolute
path from another drive sends it walking toward the filesystem root looking for
config, which can fail outright on protected system directories.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
