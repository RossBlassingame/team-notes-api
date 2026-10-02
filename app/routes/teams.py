from fastapi import APIRouter, HTTPException, status
from fastapi.exceptions import RequestValidationError

from app.auth import CurrentUser
from app.db import Conn, now
from app.policy import is_member
from app.schemas import MemberAdd, RowId, TeamCreate, TeamList, TeamOut, UsernamePath

router = APIRouter(prefix="/teams", tags=["teams"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_team(payload: TeamCreate, user: CurrentUser, conn: Conn) -> TeamOut:
    created_at = now()
    with conn:  # the team and its first member are created together or not at all
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
    if not is_member(conn, team_id, user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")
    member = conn.execute(
        "SELECT id FROM users WHERE username = :username", {"username": payload.username}
    ).fetchone()
    if member is None:
        # Same shape as FastAPI's own 422s, so clients parse one error format.
        raise RequestValidationError(
            [{"type": "value_error", "loc": ("body", "username"), "msg": "No such user"}]
        )
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO team_members (team_id, user_id, added_at)"
            " VALUES (:team_id, :user_id, :ts)",
            {"team_id": team_id, "user_id": member["id"], "ts": now()},
        )


@router.delete("/{team_id}/members/{username}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(team_id: RowId, username: UsernamePath, user: CurrentUser, conn: Conn) -> None:
    """Remove a member, or yourself to leave. Their access to the team's notes ends at once.

    Membership is flat: any member can add or remove anyone. Notes the removed member owns
    stay shared with the team until they unshare them.
    """
    if not is_member(conn, team_id, user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")
    params = {"team_id": team_id, "username": username}
    with conn:
        # One statement, so two members leaving at once can't empty the team.
        cursor = conn.execute(
            """
            DELETE FROM team_members
            WHERE team_id = :team_id
              AND user_id = (SELECT id FROM users WHERE username = :username)
              AND (SELECT COUNT(*) FROM team_members WHERE team_id = :team_id) > 1
            """,
            params,
        )
    if cursor.rowcount == 0:
        still_member = conn.execute(
            "SELECT 1 FROM team_members m JOIN users u ON u.id = m.user_id"
            " WHERE m.team_id = :team_id AND u.username = :username",
            params,
        ).fetchone()
        if still_member:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "A team needs at least one member; it can't be left empty"
            )
