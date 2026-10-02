# Team Notes API: Design Plan

A two-hour take-home: a REST backend for notes that several small teams use and share. This file records the decisions made before any code was written. The README holds the final write-up.

> **Note:** this file is kept as originally written, so parts are out of date. In particular, member removal was added after code review, and writes now use `BEGIN IMMEDIATE`. The README and the code describe the current behaviour.

## Scope

**In scope:**
- users with token auth
- teams and membership
- private notes
- sharing a note with any number of the owner's teams
- protection against lost updates
- search and pagination

**Out of scope:**
- a real identity provider
- roles
- removing members or deleting teams
- note history
- real-time collaboration
- attachments and tags
- full-text ranking
- rate limiting
- migrations
- Docker

## Stack

Python 3.12, FastAPI (`fastapi[standard]`), SQLite through the stdlib `sqlite3` module with hand-written SQL, uv, ruff, pytest and GitHub Actions. It runs with one command and needs no other services, so reviewers can start it and try it at `/docs`.

- **Entry point:** `app/main.py` exposes `app = create_app()`. `create_app(db_path)` creates the schema immediately rather than in lifespan, so it doesn't matter whether a `TestClient` is used as a context manager.
- **Database path:** `NOTES_DB_PATH`, default `./notes.db`.
- **`.gitignore`:** `*.db`, `*.db-wal`, `*.db-shm`, `.venv/`, `__pycache__/`.

## Data model

Every commit adds only its own tables with `CREATE TABLE IF NOT EXISTS`, so each change only adds things and each commit's diff matches its message.

```sql
users        (id PK AUTOINCREMENT, username TEXT UNIQUE COLLATE NOCASE, token_hash TEXT UNIQUE, created_at)  -- commit 4
notes        (id PK AUTOINCREMENT, owner_id → users, title, body DEFAULT '', version INT DEFAULT 1,
              created_at, updated_at)                                                                       -- commit 5
teams        (id PK AUTOINCREMENT, name, created_by → users, created_at)                                    -- commit 8
team_members (team_id → teams, user_id → users, added_at, PK(team_id, user_id))                             -- commit 8
note_shares  (note_id → notes ON DELETE CASCADE, team_id → teams, shared_at, PK(note_id, team_id))          -- commit 9
```

- Every column is `NOT NULL`.
- Indexes on `notes(owner_id)`, `team_members(user_id)` and `note_shares(team_id)`.
- Timestamps use `datetime.now(UTC).isoformat(timespec="microseconds")`, so they all have the same length and sort correctly.

**Validation:**

| Field | Rule |
|---|---|
| `username` | 1–32 characters, `[A-Za-z0-9_.-]` |
| team `name` | 1–100 characters |
| `title` | 1–200 characters, on both create and PATCH |
| `body` | at most 100,000 characters |

## API

| Endpoint | Who | Result |
|---|---|---|
| `GET /health` | anyone | `200 {"status":"ok"}` |
| `POST /users {username}` | anyone | `201 {id, username, token}`. The token is shown only once; only its SHA-256 hash is stored. A duplicate username returns 409. |
| `GET /users/me` | signed in | `200` with the caller's user record |
| `POST /teams {name}` | signed in | `201` with the team. The creator becomes a member in the same transaction. |
| `GET /teams` | signed in | `200` with the caller's teams |
| `POST /teams/{id}/members {username}` | a member | `204` every time (idempotent). An unknown username returns 422. |
| `POST /notes {title, body?}` | signed in | `201` with the note, plus `Location` and `ETag` headers. Notes always start private. |
| `GET /notes?q=&limit=&offset=` | signed in | `200 {items, limit, offset}` with notes the caller can see, each listed once |
| `GET /notes/{id}` | a reader | `200` with the note, plus an `ETag` header |
| `PATCH /notes/{id} {title?, body?}` | a reader | `200` with the note, plus the new `ETag`. Requires `If-Match`. |
| `DELETE /notes/{id}` | the owner | `204`. The note's shares are deleted with it. |
| `PUT /notes/{id}/shares/{team_id}` | the owner, who must be a member of that team | `201` when the share is new, `204` when it already existed. No response body. |
| `DELETE /notes/{id}/shares/{team_id}` | the owner | `204` whether or not the share existed |

**A note looks like this:**
```
{id, owner_id, title, body, version, created_at, updated_at, shared_with: [team_id…]}
```
`shared_with` is added in commit 9. It is sorted, and is `[]` when the note is private.

**Response-shape changes by commit:**
- Commit 5's list returns `{items}`.
- Commit 10 adds `limit` and `offset`.

### Rules

**Access:**
- One SQL fragment in `policy.py` decides who can see a note. It is wrapped in brackets and ANDed onto **every** note query: list, get, the PATCH `UPDATE`, and the follow-up lookup after an update that changed no rows.
  ```
  (n.owner_id = :me OR EXISTS (SELECT 1 FROM note_shares s JOIN team_members m ON m.team_id = s.team_id
                               WHERE s.note_id = n.id AND m.user_id = :me))
  ```
- It uses `EXISTS` rather than a join, so a note shared with two of the caller's teams appears once.
- The fragment starts as owner-only in commit 5 and gains the `EXISTS` clause in commit 9.
- A reader can edit content. Only the owner can delete a note or change its shares.

**Status codes:**
- If the caller can't read a note, they get **404** for every operation on it, so a status code never reveals that the note exists.
- If they can read it but the action is owner-only, they get **403**.
- Sharing to a team the caller isn't in returns 404 "team not found".
- A 401 response includes `WWW-Authenticate: Bearer`.

**PATCH:**
- Unknown fields are rejected (`extra="forbid"`).
- An explicit `null` returns 422, and so does `{}`.

**Concurrency:**
- The `ETag` is `"<version>"`, and `version` counts **content** edits (title and body) only.
- PATCH must send `If-Match`. A missing header returns **428**. Anything other than the exact current tag returns **412**; weak tags, `*` and lists of tags aren't supported, and the README says so.
- The write is `UPDATE … SET version = version + 1 … WHERE id = :id AND version = :v AND <access>`. If no row was updated, look the note up again with the same access check: 404 if it can't be seen, otherwise 412.
- Checks run in this order: 401 → 422 → 404 → 428 → 412.
- Sharing doesn't change `version` or `updated_at`. If it did, an owner who shared a note would get a 412 on their own next edit, and every other editor would too. The cost is that the ETag doesn't cover `shared_with`. That's acceptable because the ETag only guards content edits, and we don't support `If-None-Match` caching.

**Shares:**
- Shares are created with `INSERT OR IGNORE`; `rowcount` decides between 201 and 204.
- Shares don't take `If-Match`, because they are idempotent set operations.

**Lists:**
- Sorted by `updated_at DESC, id DESC`.
- `limit` is 1–100 (default 20) and `offset` is 0 or more.
- `q` is a case-insensitive substring match on title and body, ASCII only, using `LIKE :q ESCAPE '\'` with `\`, `%` and `_` escaped.

**`shared_with` visibility:** every reader sees the full list of team ids, so they know which teams can see the note. Only the ids are exposed, not team names or members.

### Implementation gotchas (verified on FastAPI 0.142, Python 3.12, SQLite 3.51)

- **Where to commit.** FastAPI runs a dependency's cleanup code after the response has already been sent. So each unit of work commits inside a `with conn:` block in the request path, and the dependency only closes the connection.
- **One connection per request**, opened with `check_same_thread=False`. Sync endpoints and dependencies can run on different threads.
- **Pragmas on every connection:** `foreign_keys=ON`, WAL, and `busy_timeout=5000`.
- **Named parameters everywhere.** Mixing `?` and `:name` placeholders breaks.
- **`AUTOINCREMENT`.** Without it SQLite reuses a deleted id, so a stale ETag could match a new note.
- **`If-Match` header.** Declare it as `Header(None)` and raise 428 yourself; a required header would make FastAPI return 422.
- **`shared_with`.** Fetch it with a `json_group_array` subquery inside the same query, so there's no extra query per note, then sort it in Python.
- **Tests** use a `tmp_path` file database, not `:memory:`.

## Tests and verification

**1. The pytest suite.**
- Each test builds `TestClient(create_app(tmp_path / "t.db"))`: a fresh database file, real HTTP calls, no mocks.
- Every commit ships its own tests. `ruff check`, `ruff format --check` and `pytest` must all pass before each commit.

What it covers:
- **Auth:**
  - One parameterised test checks that every protected route returns 401 without a token or with a bad one.
  - A duplicate username returns 409, case-insensitive.
  - An invalid username returns 422.
- **Notes:**
  - Create, read, update and delete.
  - Create returns `Location` and `ETag`.
  - Title limits on create and PATCH.
  - 422 for `null`, for `{}`, and for an unknown field.
  - Another user gets 404 on GET, PATCH and DELETE.
- **Concurrency:**
  - 428 with no header; 412 for a stale tag.
  - The ETag a PATCH returns works for the next PATCH.
  - Two writers both read version 1, and the second gets 412.
  - PATCH after DELETE returns 404.
  - A non-reader sending no tag, or a stale one, gets 404, never 428 or 412.
- **Teams:**
  - The creator is a member.
  - The list shows only the caller's own teams.
  - A non-member gets 404 when trying to add someone.
  - Adding a member is idempotent.
  - An unknown username returns 422; a username in different letter case still matches.
- **Sharing:**
  - A note shared with team T1 and team T2 can be read and edited by members of each.
  - Unsharing from T1 removes access for T1 members only, including PATCH returning 404, and leaves T2 intact.
  - The first PUT returns 201; a repeat returns 204.
  - Deleting a share that doesn't exist returns 204.
  - A reader who isn't the owner gets 403 on a share call and 403 on DELETE of the note.
  - A non-reader gets 404.
  - A team the caller isn't in returns 404.
  - Sharing leaves the owner's ETag valid: share, then PATCH with the old tag, returns 200.
  - Deleting a note deletes its shares.
  - A note shared with two of the caller's teams is listed once.
  - `shared_with` is `[]` for a private note, and sorted otherwise.
- **No leaks:** other users' private notes never appear in a list or in `q` results.
- **Search:**
  - Matches title and body, case-insensitive.
  - `%`, `_` and `\` are treated as literal characters.
  - A `limit` out of bounds returns 422.
  - Ordering and offset work.

**2. CI.** GitHub Actions runs `uv sync --locked`, ruff and pytest from a clean checkout.

**3. Smoke test, before the README commit.** Start the server with `uv run fastapi dev` and run the curl walkthrough from the local README draft against it:
- alice and bob create a team
- alice shares a note
- bob edits it
- alice's stale edit gets 412

**4. Fresh-clone check, after the README commit.** Clone the pushed repo into `/tmp` and follow the final README exactly. If something needs fixing, it goes in commit 12, and that same commit adds itself to the README's commit list. A commit can list its own subject; it just can't include its own hash.

**What none of this proves:** behaviour under parallel load on SQLite. The race test is sequential. That's valid because the version check and the write are one SQL statement, and the README will say so.

## Commits

Each commit is a small vertical slice and must pass all checks.

```
 1 docs: add design plan
 2 chore: scaffold FastAPI service with health check and tooling   (includes a stub README: run and test)
 3 ci: run lint and tests on GitHub Actions
 4 feat(users): add registration and bearer-token auth
 5 feat(notes): add create, read, and list for private notes
 6 feat(notes): add update and delete for private notes
 7 feat(notes): require If-Match on updates to prevent lost updates
 8 feat(teams): add teams and membership
 9 feat(notes): share notes with multiple teams
10 feat(notes): add search and pagination to note listing
11 docs: write README with design choices and tradeoffs
```

- **Subject line:** imperative, at most about 60 characters.
- **Body:** optional, 1–3 lines explaining *why*. No lists of changed files, and no AI trailers; AI use is disclosed once, in the README.
- **Commit 6** ships PATCH without the version check. Commit 7 adds the check and updates commit 6's tests to match.
- **Git setup:** `git init -b main`, with this repo-local identity: `Ross Blassingame <11722555+RossBlassingame@users.noreply.github.com>`. Push after each commit to https://github.com/RossBlassingame/team-notes-api (public).

## README outline

Keep it short enough to scan.
- Quickstart and curl walkthrough
- API table and access rules
- Three design choices:
  1. Sharing and authorization model
  2. Lost-update protection using `If-Match`
  3. Minimal storage, auth and scope
- Known limitations:
  - **Removing someone from a team isn't possible**, so access can't be revoked. Any member can add anyone, and that person can then edit every note shared with the team.
  - Case-insensitive matching covers ASCII only.
  - SQLite allows one writer at a time.
  - There are no migrations.
  - `If-Match` support is minimal.
- What I'd change with more time
- Commit history (the subjects)
- A short note on AI use

## Time and cuts

- **Estimate:** about 90 minutes to build commits 2–10, and about 25 minutes for the README, smoke test and fresh-clone check. That's roughly 115–120 minutes after "go", so it's tight.
- **Checkpoint 1:** if commit 9 isn't done by minute 80, skip commit 10's `q` search, ship pagination only, and rename commit 10 to `feat(notes): add pagination to note listing`.
- **Checkpoint 2:** start the README at minute 90, whatever state the code is in. Anything unfinished goes under "with more time".
