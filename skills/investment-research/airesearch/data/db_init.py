#!/usr/bin/env python
"""research.db schema — one SQLite file, one table per record type.

Every statement is CREATE IF NOT EXISTS, so any layer can call init_db() at any
time without caring whether another layer got there first. That matters because
the skills are installed and run independently: whichever one the user reaches
for first has to be able to create what it needs.

List columns from schema.py (risks, falsifiers, scenarios, ...) are stored as
JSON text in `*_json` columns. SQLite has no array type, and these are read back
whole rather than queried element-wise.

fact_log is deliberately absent here: factcontract/store.py creates it itself so
the Fact contract can run standalone, without this module having been imported.
"""

import logging
import sqlite3
from pathlib import Path

from ..paths import default_db_path

_log = logging.getLogger(__name__)

DEFAULT_DB_PATH = default_db_path()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL CHECK (length(ticker) > 0),
    entry_path      TEXT NOT NULL,
    source_note     TEXT NOT NULL DEFAULT '',
    market          TEXT NOT NULL CHECK (length(market) > 0),
    raw_rationale   TEXT NOT NULL CHECK (length(raw_rationale) > 0),
    discovered_at   TEXT NOT NULL,
    screened        INTEGER NOT NULL DEFAULT 0,
    profile_used    TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);
CREATE INDEX IF NOT EXISTS idx_candidates_ticker ON candidates(ticker);
CREATE INDEX IF NOT EXISTS idx_candidates_market ON candidates(market);

CREATE TABLE IF NOT EXISTS theses (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id        INTEGER NOT NULL REFERENCES candidates(id),
    business_overview   TEXT NOT NULL CHECK (length(business_overview) > 0),
    management          TEXT NOT NULL DEFAULT '',
    competitors         TEXT NOT NULL DEFAULT '',
    tam                 TEXT NOT NULL DEFAULT '',
    risks_json          TEXT NOT NULL CHECK (risks_json NOT IN ('', '[]')),
    variant_perception  TEXT NOT NULL DEFAULT '',
    falsifiers_json     TEXT NOT NULL DEFAULT '[]',
    data_sources_json   TEXT NOT NULL DEFAULT '[]',
    authored_at         TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);
CREATE INDEX IF NOT EXISTS idx_theses_candidate ON theses(candidate_id);

CREATE TABLE IF NOT EXISTS valuations (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    thesis_id               INTEGER NOT NULL REFERENCES theses(id),
    scenarios_json          TEXT NOT NULL DEFAULT '[]',
    discount_rate_source    TEXT NOT NULL DEFAULT '',
    html_artifact_path      TEXT NOT NULL DEFAULT '',
    valued_at               TEXT NOT NULL DEFAULT '',
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);
CREATE INDEX IF NOT EXISTS idx_valuations_thesis ON valuations(thesis_id);

CREATE TABLE IF NOT EXISTS verdicts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    valuation_id    INTEGER NOT NULL REFERENCES valuations(id),
    mode            TEXT NOT NULL,
    votes_json      TEXT NOT NULL DEFAULT '[]',
    dissent_map     TEXT NOT NULL DEFAULT '',
    authored_at     TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);
CREATE INDEX IF NOT EXISTS idx_verdicts_valuation ON verdicts(valuation_id);

CREATE TABLE IF NOT EXISTS portfolios (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    valuation_id                INTEGER NOT NULL REFERENCES valuations(id),
    sizing_method               TEXT NOT NULL,
    recommended_position_pct    REAL NOT NULL,
    kelly_inputs_json           TEXT NOT NULL DEFAULT '{}',
    sized_at                    TEXT NOT NULL DEFAULT '',
    created_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);
CREATE INDEX IF NOT EXISTS idx_portfolios_valuation ON portfolios(valuation_id);

CREATE TABLE IF NOT EXISTS sellchecks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    thesis_id       INTEGER NOT NULL REFERENCES theses(id),
    trigger         TEXT NOT NULL,
    diff_summary    TEXT NOT NULL,
    rechecked_at    TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);
CREATE INDEX IF NOT EXISTS idx_sellchecks_thesis ON sellchecks(thesis_id);

-- UNIQUE(key, domain, as_of) so an adapter re-fetching the same observation
-- replaces it rather than appending. Without it the obvious INSERT-on-miss
-- accumulates duplicate rows, and a lookup that forgets to order by recency
-- hands back the oldest value: a stale price flowing toward the Fact contract.
CREATE TABLE IF NOT EXISTS market_cache (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT NOT NULL,
    domain      TEXT NOT NULL,
    value_json  TEXT NOT NULL,
    as_of       TEXT NOT NULL,
    source      TEXT NOT NULL,
    freq        TEXT NOT NULL,
    cached_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    UNIQUE(key, domain, as_of)
);
CREATE INDEX IF NOT EXISTS idx_market_cache_key ON market_cache(key, domain);

CREATE TABLE IF NOT EXISTS calibration_memory (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    subsystem       TEXT NOT NULL,
    draft_value     TEXT NOT NULL,
    actual_value    TEXT NOT NULL,
    delta_note      TEXT NOT NULL DEFAULT '',
    recorded_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);
CREATE INDEX IF NOT EXISTS idx_calibration_subsystem ON calibration_memory(subsystem);
"""


def connect(db_path: Path = None) -> sqlite3.Connection:
    """Open a connection with the settings every store in this package needs.

    Foreign keys have to be switched on per connection: SQLite defaults them off
    for backward compatibility, which makes every REFERENCES clause in the schema
    above decorative. Without this, a thesis can name a candidate that never
    existed, and nothing complains until a later lookup quietly returns nothing.
    """
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    # timeout matches factcontract/store.py: both write the same file, and
    # mismatched lock timeouts make one of them give up while the other waits.
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path = None) -> None:
    """Create every table that does not already exist. Safe to call repeatedly.

    Also reports pre-existing orphans. Foreign keys are enforced per connection
    and are not retroactive, so a database written before enforcement was added
    can hold rows that would be rejected today. Silently carrying them would
    make the guarantee this package advertises untrue for exactly the files most
    likely to need it.
    """
    db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        conn.commit()
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            _log.warning(
                "%s holds %d row(s) referencing records that do not exist. They "
                "predate foreign-key enforcement and are skipped on read: %s",
                db_path, len(violations),
                ", ".join(f"{v[0]} id={v[1]}" for v in violations[:5]),
            )
    finally:
        conn.close()
