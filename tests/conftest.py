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
