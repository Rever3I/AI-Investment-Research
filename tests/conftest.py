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
    database, and the only sign is a file that reappears after a test run. This
    makes that impossible rather than relying on every future test remembering.
    """
    from skills._lib.data import db_init, store_support

    scratch = tmp_path / "record-store" / "research.db"
    monkeypatch.setattr(db_init, "DEFAULT_DB_PATH", scratch)
    monkeypatch.setattr(store_support, "DEFAULT_DB_PATH", scratch)
    return scratch
