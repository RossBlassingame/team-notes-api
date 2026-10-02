import json
import re
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Response, status

from app.auth import CurrentUser, User
from app.db import Conn, now
from app.policy import CAN_READ, is_member
from app.schemas import MAX_INT, NoteCreate, NoteList, NoteOut, NoteUpdate, RowId

router = APIRouter(prefix="/notes", tags=["notes"])

SELECT_NOTE = """
    SELECT n.id, n.owner_id, n.title, n.body, n.version, n.created_at, n.updated_at,
           (SELECT json_group_array(ns.team_id) FROM note_shares ns WHERE ns.note_id = n.id)
               AS shared_with
    FROM notes n
"""


# SQLite's LIKE has no default escape character, so user input needs one to match literally.
MATCHES_QUERY = r"(n.title LIKE :pattern ESCAPE '\' OR n.body LIKE :pattern ESCAPE '\')"


def like_pattern(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def etag(version: int) -> str:
    return f'"{version}"'


def expected_version(if_match: str | None) -> int:
    """The version the client last read, from its If-Match header.

    Only a single strong ETag is supported. A weak tag, `*`, or a list can never match,
    so it gets 412 like any other stale value.
    """
    if if_match is None:
        raise HTTPException(
            status.HTTP_428_PRECONDITION_REQUIRED,
            "Send If-Match with the ETag from your last read of this note",
        )
    # Exactly the form we issue: "1", "2", ... (no leading zeros; bounded to fit SQLite).
    match = re.fullmatch(r'"([1-9]\d{0,17})"', if_match.strip())
    if match is None:
        raise stale_note()
    return int(match.group(1))


def stale_note() -> HTTPException:
    return HTTPException(
        status.HTTP_412_PRECONDITION_FAILED,
        "Note changed since you last read it; fetch it again and reapply your edit",
    )


def to_note(row: sqlite3.Row) -> NoteOut:
    # json_group_array order isn't guaranteed; sort so responses are stable.
    return NoteOut(**{**dict(row), "shared_with": sorted(json.loads(row["shared_with"]))})


def require_owner(note: NoteOut, user: User) -> None:
    if note.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the note's owner can do this")


def fetch_note(conn: sqlite3.Connection, note_id: int, user_id: int) -> NoteOut:
    row = conn.execute(
        f"{SELECT_NOTE} WHERE n.id = :id AND {CAN_READ}", {"id": note_id, "me": user_id}
    ).fetchone()
    if row is None:
        # Same answer for "doesn't exist" and "not yours", so ids leak nothing.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Note not found")
    return to_note(row)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_note(payload: NoteCreate, user: CurrentUser, conn: Conn, response: Response) -> NoteOut:
    timestamp = now()
    with conn:
        cursor = conn.execute(
            "INSERT INTO notes (owner_id, title, body, created_at, updated_at)"
            " VALUES (:owner_id, :title, :body, :ts, :ts)",
            {"owner_id": user.id, "title": payload.title, "body": payload.body, "ts": timestamp},
        )
    note = fetch_note(conn, cursor.lastrowid, user.id)
    response.headers["Location"] = f"/notes/{note.id}"
    response.headers["ETag"] = etag(note.version)
    return note


@router.get("")
def list_notes(
    user: CurrentUser,
    conn: Conn,
    q: Annotated[
        str | None, Query(max_length=200, description="Case-insensitive text in title or body")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=MAX_INT)] = 0,
) -> NoteList:
    """Notes you can read, most recently updated first."""
    where = CAN_READ
    params: dict[str, object] = {"me": user.id, "limit": limit, "offset": offset}
    if q:
        where += f" AND {MATCHES_QUERY}"
        params["pattern"] = like_pattern(q)
    rows = conn.execute(
        f"{SELECT_NOTE} WHERE {where}"
        " ORDER BY n.updated_at DESC, n.id DESC LIMIT :limit OFFSET :offset",
        params,
    ).fetchall()
    return NoteList(items=[to_note(row) for row in rows], limit=limit, offset=offset)


@router.get("/{note_id}")
def get_note(note_id: RowId, user: CurrentUser, conn: Conn, response: Response) -> NoteOut:
    note = fetch_note(conn, note_id, user.id)
    response.headers["ETag"] = etag(note.version)
    return note


@router.patch("/{note_id}")
def update_note(
    note_id: RowId,
    payload: NoteUpdate,
    user: CurrentUser,
    conn: Conn,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> NoteOut:
    # Order matters: a note you can't read is 404 whatever you send, so 428/412 never
    # confirm that it exists.
    fetch_note(conn, note_id, user.id)
    version = expected_version(if_match)
    with conn:
        # Check and write in one statement, so two concurrent edits can't both succeed.
        cursor = conn.execute(
            f"""
            UPDATE notes AS n
            SET title = COALESCE(:title, title),
                body = COALESCE(:body, body),
                version = version + 1,
                updated_at = :ts
            WHERE n.id = :id AND n.version = :version AND {CAN_READ}
            """,
            {
                "title": payload.title,
                "body": payload.body,
                "ts": now(),
                "id": note_id,
                "version": version,
                "me": user.id,
            },
        )
    if cursor.rowcount == 0:
        fetch_note(conn, note_id, user.id)  # 404 if it was deleted or unshared meanwhile
        raise stale_note()
    note = fetch_note(conn, note_id, user.id)
    response.headers["ETag"] = etag(note.version)
    return note


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: RowId, user: CurrentUser, conn: Conn) -> None:
    require_owner(fetch_note(conn, note_id, user.id), user)
    with conn:
        conn.execute("DELETE FROM notes WHERE id = :id", {"id": note_id})  # shares cascade


@router.put(
    "/{note_id}/shares/{team_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={201: {"description": "Shared"}, 204: {"description": "Already shared"}},
)
def share_note(
    note_id: RowId, team_id: RowId, user: CurrentUser, conn: Conn, response: Response
) -> None:
    require_owner(fetch_note(conn, note_id, user.id), user)
    if not is_member(conn, team_id, user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")
    with conn:
        # Sharing changes who can see the note, not its content, so the version (and
        # ETag) stays put and nobody's in-progress edit is invalidated.
        cursor = conn.execute(
            "INSERT OR IGNORE INTO note_shares (note_id, team_id, shared_at)"
            " VALUES (:note_id, :team_id, :ts)",
            {"note_id": note_id, "team_id": team_id, "ts": now()},
        )
    if cursor.rowcount:
        response.status_code = status.HTTP_201_CREATED


@router.delete("/{note_id}/shares/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def unshare_note(note_id: RowId, team_id: RowId, user: CurrentUser, conn: Conn) -> None:
    require_owner(fetch_note(conn, note_id, user.id), user)
    with conn:
        conn.execute(
            "DELETE FROM note_shares WHERE note_id = :note_id AND team_id = :team_id",
            {"note_id": note_id, "team_id": team_id},
        )
