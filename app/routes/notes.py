import sqlite3

from fastapi import APIRouter, HTTPException, Response, status

from app.auth import CurrentUser
from app.db import Conn, now
from app.policy import CAN_READ
from app.schemas import NoteCreate, NoteList, NoteOut

router = APIRouter(prefix="/notes", tags=["notes"])

SELECT_NOTE = """
    SELECT n.id, n.owner_id, n.title, n.body, n.version, n.created_at, n.updated_at
    FROM notes n
"""


def etag(version: int) -> str:
    return f'"{version}"'


def fetch_note(conn: sqlite3.Connection, note_id: int, user_id: int) -> NoteOut:
    row = conn.execute(
        f"{SELECT_NOTE} WHERE n.id = :id AND {CAN_READ}", {"id": note_id, "me": user_id}
    ).fetchone()
    if row is None:
        # Same answer for "doesn't exist" and "not yours", so ids leak nothing.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Note not found")
    return NoteOut(**row)


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
def list_notes(user: CurrentUser, conn: Conn) -> NoteList:
    rows = conn.execute(
        f"{SELECT_NOTE} WHERE {CAN_READ} ORDER BY n.updated_at DESC, n.id DESC",
        {"me": user.id},
    ).fetchall()
    return NoteList(items=[NoteOut(**row) for row in rows])


@router.get("/{note_id}")
def get_note(note_id: int, user: CurrentUser, conn: Conn, response: Response) -> NoteOut:
    note = fetch_note(conn, note_id, user.id)
    response.headers["ETag"] = etag(note.version)
    return note
