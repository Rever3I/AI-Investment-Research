#!/usr/bin/env python
"""Persistence for Portfolio records.

research-portfolio writes here. The record keeps the inputs the size was derived
from, not just the answer: a position weight with no visible probabilities
behind it is a number nobody can argue with later, including the person who
produced it.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

from .schema import Portfolio
from .store_support import (
    connect,
    dumps,
    loads,
    materialise,
    materialise_one,
    open_for_read,
    open_for_write,
)

_TABLE = "portfolios"

_NEWEST_FIRST = "ORDER BY COALESCE(NULLIF(sized_at, ''), created_at) DESC, id DESC"


def _to_portfolio(row: sqlite3.Row) -> Portfolio:
    return Portfolio(
        valuation_id=row["valuation_id"],
        sizing_method=row["sizing_method"],
        recommended_position_pct=row["recommended_position_pct"],
        kelly_inputs=loads(row["kelly_inputs_json"], dict),
        sized_at=row["sized_at"],
        id=row["id"],
    )


def save_portfolio(portfolio: Portfolio, db_path: Path = None) -> int:
    """Persist a Portfolio, stamp its row id onto it, and return that id."""
    path = open_for_write(db_path)
    with closing(connect(path)) as conn:
        exists = conn.execute(
            "SELECT 1 FROM valuations WHERE id = ?", (portfolio.valuation_id,)
        ).fetchone()
        if exists is None:
            raise ValueError(
                f"No valuation with id {portfolio.valuation_id}. Run "
                f"research-valuation first: a position size needs the scenario "
                f"probabilities it was derived from."
            )
        cur = conn.execute(
            """INSERT INTO portfolios
               (valuation_id, sizing_method, recommended_position_pct,
                kelly_inputs_json, sized_at)
               VALUES (?, ?, ?, ?, ?)""",
            (portfolio.valuation_id, portfolio.sizing_method,
             portfolio.recommended_position_pct, dumps(portfolio.kelly_inputs),
             portfolio.sized_at),
        )
        conn.commit()
        portfolio.id = cur.lastrowid
        return portfolio.id


def get_portfolio(portfolio_id: int, db_path: Path = None):
    """Return one Portfolio by row id, or None if there is no such row."""
    path = open_for_read(db_path, _TABLE)
    with closing(connect(path)) as conn:
        row = conn.execute(
            "SELECT * FROM portfolios WHERE id = ?", (portfolio_id,)
        ).fetchone()
    return materialise_one(row, _to_portfolio, _TABLE)


def get_portfolio_for_valuation(valuation_id: int, db_path: Path = None):
    """Return the current sizing for a valuation, or None if it has none."""
    path = open_for_read(db_path, _TABLE)
    with closing(connect(path)) as conn:
        rows = conn.execute(
            f"SELECT * FROM portfolios WHERE valuation_id = ? {_NEWEST_FIRST}",
            (valuation_id,),
        ).fetchall()
    found = materialise(rows, _to_portfolio, _TABLE)
    return found[0] if found else None


def list_portfolios(db_path: Path = None, limit: int = None) -> list:
    """Return persisted Portfolios, newest first, skipping unreadable rows."""
    path = open_for_read(db_path, _TABLE)
    sql = f"SELECT * FROM portfolios {_NEWEST_FIRST}"
    params = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))

    with closing(connect(path)) as conn:
        rows = conn.execute(sql, params).fetchall()
    return materialise(rows, _to_portfolio, _TABLE)
