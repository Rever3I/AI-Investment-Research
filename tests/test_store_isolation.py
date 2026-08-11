"""The test-isolation guard, tested.

conftest redirects the record stores' default database so that a store call
which forgets `db_path` cannot write into the developer's real one. That claim
was previously only a docstring. It holds because every store resolves through
`store_support.resolve()`, which reads `db_init.DEFAULT_DB_PATH` through the
module rather than binding its value at import.

A store written as `from .db_init import DEFAULT_DB_PATH` would bind the real
path at import time and escape the fixture entirely, so the rule is checked here
rather than left to whoever writes the next store remembering it.
"""

import ast
from pathlib import Path

import pytest

from skills._lib.data import db_init, store_support
from skills._lib.data.candidate_store import list_candidates, save_candidate
from skills._lib.data.schema import Candidate
from skills._lib.data.thesis_store import save_thesis
from skills._lib.data.schema import Thesis

_DATA_DIR = Path(store_support.__file__).resolve().parent
_REAL_DB = Path(__file__).resolve().parent.parent / "db" / "research.db"


def _candidate():
    return Candidate(
        ticker="PROBE", entry_path="screen", source_note="x", market="US",
        raw_rationale="isolation probe", discovered_at="2026-08-04T12:00:00Z",
    )


def test_a_store_call_with_no_db_path_lands_in_the_scratch_database(
    isolated_record_store,
):
    save_candidate(_candidate())
    assert isolated_record_store.exists()
    assert [c.ticker for c in list_candidates()] == ["PROBE"]


def test_a_store_call_with_no_db_path_does_not_touch_the_real_database():
    before = _REAL_DB.exists()
    save_candidate(_candidate())
    assert _REAL_DB.exists() == before, (
        "a store call without db_path reached the repo's real database"
    )


def test_the_whole_chain_stays_isolated(isolated_record_store):
    candidate_id = save_candidate(_candidate())
    save_thesis(Thesis(
        candidate_id=candidate_id, business_overview="x", management="x",
        competitors="x", tam="x", risks=["r"],
    ))
    assert isolated_record_store.exists()
    assert not _REAL_DB.exists()


def test_resolve_follows_a_redirected_default(monkeypatch, tmp_path):
    """The property the guard depends on: resolve() must read the current value,
    not one captured when store_support was imported."""
    target = tmp_path / "redirected.db"
    monkeypatch.setattr(db_init, "DEFAULT_DB_PATH", target)
    assert store_support.resolve(None) == target


@pytest.mark.parametrize(
    "module_path",
    sorted(p for p in _DATA_DIR.glob("*.py") if p.name != "db_init.py"),
    ids=lambda p: p.name,
)
def test_no_data_module_binds_the_default_path_at_import(module_path):
    """`from .db_init import DEFAULT_DB_PATH` captures a value and puts it out of
    the fixture's reach. Modules must resolve through store_support instead."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    offenders = [
        f"{module_path.name}:{node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name == "DEFAULT_DB_PATH"
    ]
    assert not offenders, (
        f"{offenders} import DEFAULT_DB_PATH by value; use store_support.resolve() "
        f"so the test fixture can redirect it"
    )
