# Team Notes API

A REST backend for notes that several small teams capture, share, and edit together.
Python 3.12, FastAPI, SQLite. Design notes written before coding are in [PLAN.md](PLAN.md).

## Quickstart

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run fastapi dev        # http://127.0.0.1:8000/docs
```

The interactive docs at `/docs` let you call every endpoint. Create a user with `POST /users`,
then click **Authorize** and paste the token it returns.
Data is stored in `./notes.db`; set `NOTES_DB_PATH` to use a different file, or delete the file
to reset.

## Tests

```bash
uv run pytest                                          # 144 tests, a few seconds
uv run ruff check . && uv run ruff format --check .
```

Tests call the real app through FastAPI's in-process `TestClient`, with a fresh SQLite file per
test. Nothing is mocked. CI runs lint and tests on pushes to `main` and on pull requests.

## Walkthrough

With the server running (needs `curl` and `jq`), two teammates share a note and collide on an edit:

```bash
BASE=http://127.0.0.1:8000
JSON='Content-Type: application/json'
ALICE=$(curl -s -X POST $BASE/users -H "$JSON" -d '{"username":"alice"}' | jq -r .token)
BOB=$(curl -s -X POST $BASE/users -H "$JSON" -d '{"username":"bob"}' | jq -r .token)

# Alice creates a team and adds Bob
TEAM=$(curl -s -X POST $BASE/teams -H "Authorization: Bearer $ALICE" -H "$JSON" \
  -d '{"name":"platform"}' | jq .id)
curl -s -o /dev/null -w '%{http_code}\n' -X POST $BASE/teams/$TEAM/members \
  -H "Authorization: Bearer $ALICE" -H "$JSON" -d '{"username":"bob"}'           # 204

# Alice writes a note. It starts private, so she shares it with the team.
NOTE=$(curl -s -X POST $BASE/notes -H "Authorization: Bearer $ALICE" -H "$JSON" \
  -d '{"title":"Roadmap","body":"Q1: auth"}' | jq .id)
curl -s -o /dev/null -w '%{http_code}\n' -X PUT $BASE/notes/$NOTE/shares/$TEAM \
  -H "Authorization: Bearer $ALICE"                                              # 201

# Bob read version 1 (ETag "1") and saves an edit
curl -s -X PATCH $BASE/notes/$NOTE -H "Authorization: Bearer $BOB" -H "$JSON" \
  -H 'If-Match: "1"' -d '{"body":"Q1: auth, search"}' | jq -c '{body, version}'
# {"body":"Q1: auth, search","version":2}

# Alice also read version 1. Her save is rejected instead of overwriting Bob's edit.
curl -s -w '\n' -X PATCH $BASE/notes/$NOTE -H "Authorization: Bearer $ALICE" -H "$JSON" \
  -H 'If-Match: "1"' -d '{"body":"Q1: auth, billing"}'
# {"detail":"If-Match doesn't match the note's current ETag; fetch it again and reapply your edit"}  (412)
```

## API

All endpoints except `GET /health` and `POST /users` need `Authorization: Bearer <token>`.

| Endpoint | Purpose |
|---|---|
| `POST /users` `{username}` | Register. Returns the token once. |
| `GET /users/me` | The caller's user record |
| `POST /teams` `{name}` | Create a team; the creator becomes a member |
| `GET /teams` | Teams you belong to |
| `POST /teams/{id}/members` `{username}` | Add someone to a team you're in (idempotent) |
| `DELETE /teams/{id}/members/{username}` | Remove a member, or yourself to leave. Their access ends immediately. The last member can't leave (`409`). |
| `POST /notes` `{title, body?}` | Create a private note → `201`, `Location`, `ETag` |
| `GET /notes?q=&limit=&offset=` | Notes you can read, most recently updated first. `q` searches title and body. |
| `GET /notes/{id}` | One note, plus its `ETag` |
| `PATCH /notes/{id}` `{title?, body?}` | Edit; **requires `If-Match`** |
| `DELETE /notes/{id}` | Delete (owner only) |
| `PUT /notes/{id}/shares/{team_id}` | Share with one of your teams → `201`, or `204` if already shared |
| `DELETE /notes/{id}/shares/{team_id}` | Unshare → `204` |

**Who can do what with a note**

| | Owner | Member of a team it's shared with | Anyone else |
|---|---|---|---|
| Read, edit content | yes | yes | `404` |
| See it in list and search results | yes | yes | not included |
| Delete, share, unshare | yes | `403` | `404` |

## Design choices

### 1. Sharing and authorization model

Notes start private. The owner can share a note with any number of teams they belong to.
Access is computed from team membership at query time and never copied, so removing someone
from a team cuts off their access on their very next request.

The most important property is that **one SQL predicate decides visibility**
([`app/policy.py`](app/policy.py)). It is ANDed into every note query: list, search, fetch,
update. A common authorization bug in APIs like this is a list or search endpoint that filters
differently from the detail endpoint. With a single predicate, that can't happen.

Status codes:
- `404` for anything you can't read, so ids reveal nothing about other people's notes.
- `403` only for notes you can already see but may not change (delete, share).

Sharing is a sub-resource, `PUT/DELETE /notes/{id}/shares/{team_id}`, rather than a PATCH
field. Content edits (any reader) and access changes (owner only) have different rules, so
they get different endpoints.

Alternatives I considered:
- One team per note: simpler, but an arbitrary limit.
- Per-user ACLs: more flexible, but more API and UI surface.
- Team-owned notes: leaves no private drafts.
- Roles: out of scope.

### 2. Preventing lost updates with ETag and If-Match

With shared notes, two people (or one person in two tabs) will edit the same note.
Last-write-wins would silently throw away someone's work.

- Each note has a `version`, exposed as a strong `ETag`.
- `PATCH` **requires** `If-Match`: a missing header returns `428`, a stale one `412`.
- The check and the write are a single conditional `UPDATE … WHERE version = :v`, so two
  concurrent saves can't both succeed.
- Making the header required, not optional, means a client can't skip the check by accident.
- Sharing doesn't change the version. It changes who sees the note, not its content, so it
  never invalidates someone's in-progress edit.

Alternatives I considered:
- Last-write-wins: silently loses edits.
- Field-level merging: more complex for little gain here.
- Pessimistic locks: a poor fit for stateless HTTP.
- CRDT/OT real-time collaboration: a different product.

### 3. Minimal storage, auth, and scope

- **Storage.** SQLite with hand-written SQL needs no setup for reviewers and still gives real
  constraints and transactions. Every query is readable in a few small files. The costs: one
  writer at a time, and no migrations. The schema is `CREATE TABLE IF NOT EXISTS`.
- **Auth.** Each user gets a random bearer token, shown once and stored only as a SHA-256 hash.
  It stands in for an identity provider; it is not meant as a design for one.
- **Scope.** I cut anything that didn't serve "capture, share, and safely co-edit notes": no
  roles, tags, history, attachments, or real-time updates. I spent the time on access rules,
  edit conflicts, and tests instead.

## Known limitations

- **Team membership is flat.** Any member can add or remove anyone, and there are no team
  admins. Leaving a team doesn't unshare the notes you shared with it; you can still unshare
  them afterwards. Teams can't be deleted.
- **Open registration.** Anyone can create a user.
- **Search is basic.** It's a substring `LIKE`: a full scan, with case-insensitive matching for
  ASCII only.
- **Offset pagination** can skip or repeat notes when notes are edited between page requests.
- **`If-Match` support is minimal.** Only a single exact strong ETag is accepted; `*`, weak
  tags, and lists get `412`. The ETag covers content only, not `shared_with`.
- **No request-size limit.** The note body is capped at 100,000 characters, but nothing caps the
  raw request size. That belongs at the reverse proxy.
- **No load testing.** The parallel-save test races 16 threads in-process. It isn't a load test.

## With more time

- **Change:**
  - Postgres with migrations, instead of SQLite and create-on-startup.
  - OIDC/JWT from a real identity provider, instead of local tokens.
  - Keyset (cursor) pagination.
- **Add:**
  - Team roles, so that only admins control membership.
  - A team-detail endpoint listing members.
  - Note history, so a `412` can offer a merge.
  - Full-text search.
  - Rate limiting.
  - RFC 9457 problem-details errors.
  - An audit log.
  - A container image.
- **Stop:**
  - Allowing open registration.
  - Exposing bare team ids in `shared_with` once teams have a readable detail view.
  - Hand-writing every SQL string once the query count grows. A thin query layer would pay off.

## Project layout

```
app/
  api.py        create_app(): wiring and schema setup
  main.py       ASGI entrypoint for `fastapi dev`
  db.py         connections, pragmas, transactions
  schema.sql    tables and indexes
  auth.py       token hashing and the current-user dependency
  policy.py     who can see a note (one SQL predicate) and team membership
  schemas.py    request and response models and validation
  routes/       users, teams, notes
tests/          one file per feature, plus an auth test generated from every route
```

## Commit history

Each commit is one vertical slice with its own tests, and lint and tests pass at every commit.

1. `docs: add design plan`
2. `chore: scaffold FastAPI service with health check and tooling`
3. `ci: run lint and tests on GitHub Actions`
4. `feat(users): add registration and bearer-token auth`
5. `feat(notes): add create, read, and list for private notes`
6. `feat(notes): add update and delete for private notes`
7. `feat(notes): require If-Match on updates to prevent lost updates`
8. `feat(teams): add teams and membership`
9. `feat(notes): share notes with multiple teams`
10. `feat(notes): add search and pagination to note listing`
11. `docs: write README with design choices and tradeoffs`

After a separate review of the code, these commits followed:

12. `fix: return 4xx instead of 500 for out-of-range ids and unencodable input`
13. `fix(notes): read back writes inside their transaction`
14. `fix: make error responses consistent`
15. `test: cover parallel saves, unsharing from lists, and shared-note search`
16. `docs: correct README claims found in code review`
17. `feat(teams): let members remove members and leave teams`

## How I used AI

I built this with Claude Code, an AI coding agent:

- **Planning.** Before any code, the agent drafted the design. Separate AI reviewers then
  critiqued it in several rounds, and the result is [PLAN.md](PLAN.md). I made the scope and
  product calls; for example, notes can be shared with multiple teams rather than one.
- **Building.** The agent wrote the code and tests in the small slices above. Lint and the full
  test suite had to pass before each commit.
- **Reviewing.** After the build, a fresh AI reviewer audited the code with reproduction
  scripts. Commits 12–16 fix what it found: several malformed inputs that returned 500s, a race
  in the read-back after an edit, inconsistent error shapes, and inaccurate claims in this
  README. Commit 17 closes the biggest gap it flagged: without a way to remove someone from a
  team, access could never be revoked.
- **Checking.** The walkthrough above was run against the live server, and the tests were run
  from a fresh clone, before committing.
- **Timing.** The agent writes code fast: commits 2–11 span about 12 minutes. Most of the time
  went into the plan, its review rounds, and the code review.
