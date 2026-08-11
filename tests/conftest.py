import pytest


@pytest.fixture(autouse=True)
def isolated_fact_store(monkeypatch, tmp_path):
    """Point the fact_log at a scratch database for every test in the suite.

    Autouse and suite-wide because verify() reaches the store even with
    record=False — it reads history for jump detection, and that read creates
    the database file. Scoped to one test module, the first test elsewhere that
    calls verify() would write fixture values into the developer's real
    db/research.db and corrupt the magnitude baseline it learns from.
    """
    from skills._lib.factcontract import store as store_mod

    monkeypatch.setattr(store_mod, "DB_PATH", tmp_path / "fact-store" / "research.db")
    return store_mod


@pytest.fixture(autouse=True)
def isolated_record_store(monkeypatch, tmp_path):
    """Repoint the record stores' default database at a scratch path.

    Tests pass an explicit db_path almost everywhere, but "almost" is the
    problem: one store call that forgets it writes into the developer's real
    database, and the only sign is a file that reappears after a test run.

    One patch point is enough because `store_support.resolve` reads
    `db_init.DEFAULT_DB_PATH` through the module rather than binding its value,
    and every store resolves through it. A store that instead did
    `from .db_init import DEFAULT_DB_PATH` would bind the real path at import
    and escape this fixture — which is why store_support documents that as
    forbidden, and why test_store_isolation.py checks the rule holds.
    """
    from skills._lib.data import db_init

    scratch = tmp_path / "record-store" / "research.db"
    monkeypatch.setattr(db_init, "DEFAULT_DB_PATH", scratch)
    return scratch
