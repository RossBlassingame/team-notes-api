"""Who can see a note: the single source of truth for note access.

Every note query ANDs `CAN_READ` in (bound with `:me`), so list, fetch, and update can
never disagree about visibility. Anyone who can read a note can edit its content; only
the owner can delete it.
"""

CAN_READ = "(n.owner_id = :me)"
