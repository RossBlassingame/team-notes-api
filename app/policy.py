"""Who can see a note: the single source of truth for note access.

Every note read (list, search, fetch) and the content update AND `CAN_READ` in (bound with
`:me`), so they can never disagree about visibility. Owner-only writes (delete, share,
unshare) first fetch the note through it, then check ownership.

You can read a note if you own it or belong to any team it is shared with. Anyone who can
read a note can edit its content; only the owner can delete it or change who it is shared
with.
"""

import sqlite3

# EXISTS rather than a JOIN, so a note shared with two of your teams still appears once.
CAN_READ = """(
    n.owner_id = :me
    OR EXISTS (
        SELECT 1 FROM note_shares s
        JOIN team_members m ON m.team_id = s.team_id
        WHERE s.note_id = n.id AND m.user_id = :me
    )
)"""


def is_member(conn: sqlite3.Connection, team_id: int, user_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM team_members WHERE team_id = :team_id AND user_id = :user_id",
        {"team_id": team_id, "user_id": user_id},
    ).fetchone()
    return row is not None
