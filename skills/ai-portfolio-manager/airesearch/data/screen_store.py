#!/usr/bin/env python
"""Persistence for saved screening criteria.

Stage 1 writes here when a user says "remember these criteria" and reads here
when they say "run my usual screen". Until this existed, `Candidate.screened`
was always False and `profile_used` was always empty, because there was nothing
a profile name could refer to.

Saving under a name that already exists replaces it. A screen is a thing users
revise — a rule gets tightened, a threshold moves — and versioning that
automatically would leave `profile_used="quality-industrials"` pointing at
several different sets of criteria with no way to tell which one ran.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

from .schema import ScreenProfile
from .store_support import (
    connect,
    dumps,
    loads,
    materialise,
    materialise_one,
    open_for_read,
    open_for_write,
)

_TABLE = "screen_profiles"


def _to_profile(row: sqlite3.Row) -> ScreenProfile:
    return ScreenProfile(
        name=row["name"],
        criteria=loads(row["criteria_json"], expect=dict),
        notes=row["notes"],
        created_at=row["created_at"],
        id=row["id"],
    )


def save_screen_profile(profile: ScreenProfile, db_path: Path = None) -> int:
    """Persist a profile, stamp its row id onto it, and return that id.

    Replaces any profile of the same name, so the id can change across saves.
    Read it back from the returned record rather than remembering an earlier one.
    """
    path = open_for_write(db_path)
    with closing(connect(path)) as conn:
        cur = conn.execute(
            """INSERT INTO screen_profiles (name, criteria_json, notes)
               VALUES (?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   criteria_json = excluded.criteria_json,
                   notes         = excluded.notes""",
            (profile.name, dumps(profile.criteria), profile.notes),
        )
        conn.commit()
        # ON CONFLICT ... DO UPDATE reports lastrowid as 0 on some builds, so ask
        # for the row rather than trusting it.
        if not cur.lastrowid:
            row = conn.execute(
                "SELECT id FROM screen_profiles WHERE name = ?", (profile.name,)
            ).fetchone()
            profile.id = row["id"] if row else None
        else:
            profile.id = cur.lastrowid
        return profile.id


def get_screen_profile(name: str, db_path: Path = None):
    """Return one profile by name, or None if no profile has that name.

    Raises UnreadableRecord if the row exists but does not satisfy the record
    contract — a criteria column edited by hand into something empty, say.
    """
    path = open_for_read(db_path, _TABLE)
    with closing(connect(path)) as conn:
        row = conn.execute(
            "SELECT * FROM screen_profiles WHERE name = ?", (str(name).strip(),)
        ).fetchone()
    return materialise_one(row, _to_profile, _TABLE)


def list_screen_profiles(db_path: Path = None) -> list:
    """Every saved profile, alphabetically, skipping any that cannot be read.

    Alphabetical rather than newest-first: this list is something a user reads to
    pick a name out of, and a stable order is what makes it scannable.
    """
    path = open_for_read(db_path, _TABLE)
    with closing(connect(path)) as conn:
        rows = conn.execute(
            "SELECT * FROM screen_profiles ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return materialise(rows, _to_profile, _TABLE)


def delete_screen_profile(name: str, db_path: Path = None) -> bool:
    """Remove a profile. Returns whether there was one to remove.

    Candidates keep their `profile_used` string afterwards. That is deliberate:
    the record of which criteria produced a candidate is a historical fact, and
    rewriting it because the profile was later deleted would edit the past.
    """
    path = open_for_read(db_path, _TABLE)
    with closing(connect(path)) as conn:
        cur = conn.execute(
            "DELETE FROM screen_profiles WHERE name = ?", (str(name).strip(),)
        )
        conn.commit()
        return cur.rowcount > 0
