CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    token_hash  TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,  -- never reuse ids, so stale ETags never match
    owner_id    INTEGER NOT NULL REFERENCES users(id),
    title       TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',
    version     INTEGER NOT NULL DEFAULT 1,         -- bumped on every content edit; the ETag
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS notes_owner_id ON notes(owner_id);
