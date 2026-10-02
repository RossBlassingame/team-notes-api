"""Who can see a note: the single source of truth for note access.

Every note query ANDs `CAN_READ` in (bound with `:me`), so list, fetch, and update can
never disagree about visibility. Anyone who can read a note can edit its content; only
the owner can delete it.
"""

import sqlite3

CAN_READ = "(n.owner_id = :me)"


def is_member(conn: sqlite3.Connection, team_id: int, user_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM team_members WHERE team_id = :team_id AND user_id = :user_id",
        {"team_id": team_id, "user_id": user_id},
    ).fetchone()
    return row is not None
