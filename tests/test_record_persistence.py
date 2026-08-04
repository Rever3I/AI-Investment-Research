"""Round-trip every record type through the DDL that will store it.

Only Candidate has a store module so far. These tests exercise the remaining
five tables directly, because the list-and-dict fields (`risks`, `falsifiers`,
`scenarios`, `votes`, `kelly_inputs`) cross a JSON-text boundary that nothing
else checks. A column-name comparison cannot catch a type mismatch there; a
write-then-read can, and it does it now rather than after five stores exist.
"""

import json
import sqlite3

import pytest

from skills._lib.data.db_init import init_db
from skills._lib.data.schema import (
    Portfolio,
    Sellcheck,
    Thesis,
    Valuation,
    Verdict,
)


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "research.db"
    init_db(db_path)
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


def test_thesis_survives_the_json_column_boundary(conn):
    original = Thesis(
        candidate_id=1,
        business_overview="Designs accelerators.",
        management="Founder-led.",
        competitors="AMD, Intel",
        tam="$400B by 2030",
        risks=["customer concentration", "export controls"],
        variant_perception="Networking attach rate is underrated.",
        falsifiers=["hyperscaler capex guides down twice running"],
        data_sources=["sec-xbrl", "10-K"],
        authored_at="2026-08-04T12:00:00Z",
    )
    conn.execute(
        """INSERT INTO theses
           (candidate_id, business_overview, management, competitors, tam,
            risks_json, variant_perception, falsifiers_json, data_sources_json,
            authored_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (original.candidate_id, original.business_overview, original.management,
         original.competitors, original.tam, json.dumps(original.risks),
         original.variant_perception, json.dumps(original.falsifiers),
         json.dumps(original.data_sources), original.authored_at),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM theses").fetchone()
    restored = Thesis.from_dict({
        "candidate_id": row["candidate_id"],
        "business_overview": row["business_overview"],
        "management": row["management"],
        "competitors": row["competitors"],
        "tam": row["tam"],
        "risks": json.loads(row["risks_json"]),
        "variant_perception": row["variant_perception"],
        "falsifiers": json.loads(row["falsifiers_json"]),
        "data_sources": json.loads(row["data_sources_json"]),
        "authored_at": row["authored_at"],
    })
    assert restored == original
    assert isinstance(restored.risks, list)


def test_valuation_scenarios_survive_the_json_column_boundary(conn):
    original = Valuation(
        thesis_id=1,
        scenarios=[
            {"name": "bull", "price_target": 250.0, "probability": 0.25, "assumptions": "g=25%"},
            {"name": "base", "price_target": 180.0, "probability": 0.50, "assumptions": "g=15%"},
            {"name": "bear", "price_target": 90.0, "probability": 0.25, "assumptions": "g=5%"},
        ],
        discount_rate_source="US 10Y + 5% ERP",
        html_artifact_path="out/nvda.html",
        valued_at="2026-08-04T12:00:00Z",
    )
    conn.execute(
        """INSERT INTO valuations
           (thesis_id, scenarios_json, discount_rate_source, html_artifact_path, valued_at)
           VALUES (?, ?, ?, ?, ?)""",
        (original.thesis_id, json.dumps(original.scenarios),
         original.discount_rate_source, original.html_artifact_path, original.valued_at),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM valuations").fetchone()
    restored = Valuation.from_dict({
        "thesis_id": row["thesis_id"],
        "scenarios": json.loads(row["scenarios_json"]),
        "discount_rate_source": row["discount_rate_source"],
        "html_artifact_path": row["html_artifact_path"],
        "valued_at": row["valued_at"],
    })
    assert restored == original
    # Probabilities must survive as floats: research-portfolio reads them
    # straight into the Kelly formula.
    assert restored.scenarios[1]["probability"] == 0.50


def test_verdict_survives_the_json_column_boundary(conn):
    original = Verdict(
        valuation_id=1,
        mode="persona_debate",
        votes=[{"voice": "bull", "call": "BUY"}, {"voice": "bear", "call": "PASS"}],
        dissent_map="Unresolved: terminal growth rate.",
        authored_at="2026-08-04T12:00:00Z",
    )
    conn.execute(
        """INSERT INTO verdicts (valuation_id, mode, votes_json, dissent_map, authored_at)
           VALUES (?, ?, ?, ?, ?)""",
        (original.valuation_id, original.mode, json.dumps(original.votes),
         original.dissent_map, original.authored_at),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM verdicts").fetchone()
    restored = Verdict.from_dict({
        "valuation_id": row["valuation_id"],
        "mode": row["mode"],
        "votes": json.loads(row["votes_json"]),
        "dissent_map": row["dissent_map"],
        "authored_at": row["authored_at"],
    })
    assert restored == original


def test_portfolio_survives_the_json_column_boundary(conn):
    original = Portfolio(
        valuation_id=1,
        sizing_method="half_kelly",
        recommended_position_pct=4.25,
        kelly_inputs={"edge": 0.18, "odds": 1.9, "probability": 0.55},
        sized_at="2026-08-04T12:00:00Z",
    )
    conn.execute(
        """INSERT INTO portfolios
           (valuation_id, sizing_method, recommended_position_pct, kelly_inputs_json, sized_at)
           VALUES (?, ?, ?, ?, ?)""",
        (original.valuation_id, original.sizing_method, original.recommended_position_pct,
         json.dumps(original.kelly_inputs), original.sized_at),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM portfolios").fetchone()
    restored = Portfolio.from_dict({
        "valuation_id": row["valuation_id"],
        "sizing_method": row["sizing_method"],
        "recommended_position_pct": row["recommended_position_pct"],
        "kelly_inputs": json.loads(row["kelly_inputs_json"]),
        "sized_at": row["sized_at"],
    })
    assert restored == original
    # Stored as REAL, not TEXT — sizing arithmetic depends on it.
    assert isinstance(restored.recommended_position_pct, float)


def test_sellcheck_survives_its_keyword_named_column(conn):
    # `trigger` is a SQL keyword; SQLite tolerates it unquoted, but nothing
    # verified that until now.
    original = Sellcheck(
        thesis_id=1,
        trigger="user_initiated",
        diff_summary="facts_changed: export licence revoked",
        rechecked_at="2026-08-04T12:00:00Z",
    )
    conn.execute(
        """INSERT INTO sellchecks (thesis_id, trigger, diff_summary, rechecked_at)
           VALUES (?, ?, ?, ?)""",
        (original.thesis_id, original.trigger, original.diff_summary, original.rechecked_at),
    )
    conn.commit()

    row = conn.execute(
        "SELECT thesis_id, trigger, diff_summary, rechecked_at FROM sellchecks"
    ).fetchone()
    assert Sellcheck.from_dict(dict(row)) == original


_TIMESTAMPED_TABLES = (
    ("candidates",
     "INSERT INTO candidates (ticker, entry_path, market, discovered_at) "
     "VALUES ('NVDA', 'screen', 'US', '2026-08-04T12:00:00+00:00')"),
    ("theses",
     "INSERT INTO theses (candidate_id) VALUES (1)"),
    ("valuations",
     "INSERT INTO valuations (thesis_id) VALUES (1)"),
    ("verdicts",
     "INSERT INTO verdicts (valuation_id, mode) VALUES (1, 'checklist')"),
    ("portfolios",
     "INSERT INTO portfolios (valuation_id, sizing_method, recommended_position_pct) "
     "VALUES (1, 'half_kelly', 1.0)"),
    ("sellchecks",
     "INSERT INTO sellchecks (thesis_id, trigger, diff_summary) "
     "VALUES (1, 'user_initiated', 'still_holds')"),
)


@pytest.mark.parametrize("table,insert_sql", _TIMESTAMPED_TABLES)
def test_created_at_defaults_are_iso_8601_utc(conn, table, insert_sql):
    """Record timestamps normalize to ISO 8601 UTC; the storage layer's own
    defaults must match, or sorting across the two formats silently misorders.

    Every table is checked, not just one: a default that drifts back on any of
    them reintroduces the same incomparable-format bug in that corner.
    """
    conn.execute(insert_sql)
    conn.commit()
    created_at = conn.execute(f"SELECT created_at FROM {table}").fetchone()[0]

    assert "T" in created_at, f"{table}: expected ISO 8601, got {created_at!r}"
    assert created_at.endswith("+00:00"), f"{table}: expected a UTC offset, got {created_at!r}"


def test_created_at_defaults_are_actually_utc_not_local_time(conn):
    """A local timestamp wearing a +00:00 suffix passes a format check while
    being hours wrong, so compare the stored value against real UTC."""
    from datetime import datetime, timezone

    before = datetime.now(timezone.utc).replace(microsecond=0)
    conn.execute(
        "INSERT INTO candidates (ticker, entry_path, market, discovered_at) "
        "VALUES ('NVDA', 'screen', 'US', '2026-08-04T12:00:00+00:00')"
    )
    conn.commit()
    created_at = conn.execute("SELECT created_at FROM candidates").fetchone()[0]

    stored = datetime.fromisoformat(created_at)
    drift = abs((stored - before).total_seconds())
    assert drift < 120, (
        f"created_at {created_at!r} is {drift:.0f}s from UTC now — "
        f"the default is probably recording local time"
    )


def test_market_cache_replaces_rather_than_duplicates_an_observation(conn):
    """A re-fetch of the same observation must overwrite, not append — otherwise
    a lookup that forgets to order by recency hands back a stale price."""
    for value in ('{"px": 100}', '{"px": 101}'):
        conn.execute(
            """INSERT OR REPLACE INTO market_cache
               (key, domain, value_json, as_of, source, freq)
               VALUES ('NVDA:close', 'us_equity', ?, '2026-08-04T20:00:00+00:00',
                       'sec-xbrl', 'daily')""",
            (value,),
        )
    conn.commit()

    rows = conn.execute("SELECT value_json FROM market_cache").fetchall()
    assert len(rows) == 1
    assert rows[0]["value_json"] == '{"px": 101}'
