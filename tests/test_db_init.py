import sqlite3
from pathlib import Path

from skills._lib.data.db_init import DEFAULT_DB_PATH, init_db

EXPECTED_TABLES = {
    "candidates", "theses", "valuations", "verdicts",
    "portfolios", "sellchecks", "market_cache", "calibration_memory",
}


def _tables(db_path):
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    conn.close()
    return {r[0] for r in rows}


def _columns(db_path, table):
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    conn.close()
    return {r[1] for r in rows}


def test_init_db_creates_all_tables(tmp_path):
    db_path = tmp_path / "research.db"
    init_db(db_path)
    assert EXPECTED_TABLES.issubset(_tables(db_path))


def test_init_db_is_idempotent(tmp_path):
    db_path = tmp_path / "research.db"
    init_db(db_path)
    init_db(db_path)  # must not raise
    assert EXPECTED_TABLES.issubset(_tables(db_path))


def test_init_db_preserves_existing_rows(tmp_path):
    db_path = tmp_path / "research.db"
    init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO candidates (ticker, entry_path, market, raw_rationale, "
        "discovered_at) VALUES ('NVDA', 'screen', 'US', 'why', "
        "'2026-08-04T12:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    init_db(db_path)  # second call must not wipe data

    conn = sqlite3.connect(str(db_path))
    n = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    conn.close()
    assert n == 1


def test_init_db_creates_parent_directory(tmp_path):
    db_path = tmp_path / "nested" / "deeper" / "research.db"
    init_db(db_path)
    assert db_path.exists()


def test_candidates_table_matches_candidate_schema(tmp_path):
    db_path = tmp_path / "research.db"
    init_db(db_path)
    cols = _columns(db_path, "candidates")
    assert {
        "ticker", "entry_path", "source_note", "market",
        "raw_rationale", "discovered_at", "screened", "profile_used",
    }.issubset(cols)


def test_theses_table_matches_thesis_schema(tmp_path):
    db_path = tmp_path / "research.db"
    init_db(db_path)
    cols = _columns(db_path, "theses")
    assert {
        "candidate_id", "business_overview", "management", "competitors",
        "tam", "risks_json", "variant_perception", "falsifiers_json",
        "data_sources_json", "authored_at",
    }.issubset(cols)


def test_valuations_table_matches_valuation_schema(tmp_path):
    db_path = tmp_path / "research.db"
    init_db(db_path)
    cols = _columns(db_path, "valuations")
    assert {
        "thesis_id", "scenarios_json", "discount_rate_source",
        "html_artifact_path", "valued_at",
    }.issubset(cols)


def test_portfolios_table_matches_portfolio_schema(tmp_path):
    db_path = tmp_path / "research.db"
    init_db(db_path)
    cols = _columns(db_path, "portfolios")
    assert {
        "valuation_id", "sizing_method", "recommended_position_pct",
        "kelly_inputs_json", "sized_at",
    }.issubset(cols)


def test_market_cache_table_supports_staleness_lookup(tmp_path):
    db_path = tmp_path / "research.db"
    init_db(db_path)
    cols = _columns(db_path, "market_cache")
    assert {"key", "domain", "value_json", "as_of", "source", "freq"}.issubset(cols)


def test_calibration_memory_table_records_draft_vs_actual(tmp_path):
    db_path = tmp_path / "research.db"
    init_db(db_path)
    cols = _columns(db_path, "calibration_memory")
    assert {"subsystem", "draft_value", "actual_value", "delta_note"}.issubset(cols)


def test_default_db_path_resolves_inside_repo():
    # db_init.py lives at <repo>/skills/_lib/data/db_init.py
    repo_root = Path(__file__).resolve().parent.parent
    assert DEFAULT_DB_PATH == repo_root / "db" / "research.db"
