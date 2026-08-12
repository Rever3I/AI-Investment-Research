"""The Fact contract — the gate every number passes before it reaches output.

A bare float cannot enter: a figure must be declared as a Fact, carrying its
unit, frequency, as-of time, and source, before verify() will adjudicate it.
"""

from .checks import FactCheckError, format_report, verify
from .fact import Fact, FactError

__all__ = ["Fact", "FactError", "verify", "FactCheckError", "format_report"]
