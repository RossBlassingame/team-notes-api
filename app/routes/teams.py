from fastapi import APIRouter, HTTPException, status
from fastapi.exceptions import RequestValidationError

from app.auth import CurrentUser
from app.db import Conn, now, write_transaction
from app.policy import is_member
from app.schemas import MemberAdd, RowId, TeamCreate, TeamList, TeamOut, UsernamePath

router = APIRouter(prefix="/teams", tags=["teams"])


def require_member(conn, team_id: int, user_id: int) -> None:
    if not is_member(conn, team_id, user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")


def find_user_id(conn, username: str, source: str) -> int:
    row = conn.execute(
        "SELECT id FROM users WHERE username = :username", {"username": username}
    ).fetchone()
    if row is None:
        # Same shape as FastAPI's own 422s, so clients parse one error format.
        raise RequestValidationError(
            [{"type": "value_error", "loc": (source, "username"), "msg": "No such user"}]
        )
    return row["id"]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_team(payload: TeamCreate, user: CurrentUser, conn: Conn) -> TeamOut:
    created_at = now()
    with write_transaction(conn):  # the team and its first member, together or not at all
        cursor = conn.execute(
            "INSERT INTO teams (name, created_by, created_at) VALUES (:name, :me, :ts)",
            {"name": payload.name, "me": user.id, "ts": created_at},
        )
        conn.execute(
            "INSERT INTO team_members (team_id, user_id, added_at) VALUES (:team_id, :me, :ts)",
            {"team_id": cursor.lastrowid, "me": user.id, "ts": created_at},
        )
    return TeamOut(
        id=cursor.lastrowid, name=payload.name, created_by=user.id, created_at=created_at
    )


@router.get("")
def list_teams(user: CurrentUser, conn: Conn) -> TeamList:
    rows = conn.execute(
        """
        SELECT t.id, t.name, t.created_by, t.created_at
        FROM teams t JOIN team_members m ON m.team_id = t.id
        WHERE m.user_id = :me
        ORDER BY t.id
        """,
        {"me": user.id},
    ).fetchall()
    return TeamList(items=[TeamOut(**row) for row in rows])


@router.post("/{team_id}/members", status_code=status.HTTP_204_NO_CONTENT)
def add_member(team_id: RowId, payload: MemberAdd, user: CurrentUser, conn: Conn) -> None:
    with write_transaction(conn):
        # Checked under the write lock: someone removed mid-request can't re-add anyone.
        require_member(conn, team_id, user.id)
        member_id = find_user_id(conn, payload.username, source="body")
        conn.execute(
            "INSERT OR IGNORE INTO team_members (team_id, user_id, added_at)"
            " VALUES (:team_id, :user_id, :ts)",
            {"team_id": team_id, "user_id": member_id, "ts": now()},
        )


@router.delete("/{team_id}/members/{username}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(team_id: RowId, username: UsernamePath, user: CurrentUser, conn: Conn) -> None:
    """Remove a member, or yourself to leave. Their access to the team's notes ends at once.

    Membership is flat: any member can add or remove anyone. Notes the removed member owns
    stay shared with the team until they unshare them.
    """
    with write_transaction(conn):
        require_member(conn, team_id, user.id)
        member_id = find_user_id(conn, username, source="path")
        if not is_member(conn, team_id, member_id):
            return  # already not a member: removal is idempotent
        member_count = conn.execute(
            "SELECT COUNT(*) FROM team_members WHERE team_id = :team_id", {"team_id": team_id}
        ).fetchone()[0]
        if member_count == 1:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "A team needs at least one member; it can't be left empty"
            )
        conn.execute(
            "DELETE FROM team_members WHERE team_id = :team_id AND user_id = :user_id",
            {"team_id": team_id, "user_id": member_id},
        )
