import sqlite3

from fastapi import APIRouter, HTTPException, status

from app.auth import CurrentUser, hash_token, new_token
from app.db import Conn, now, write_transaction
from app.schemas import UserCreate, UserCreated, UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, conn: Conn) -> UserCreated:
    token = new_token()
    created_at = now()
    try:
        with write_transaction(conn):
            cursor = conn.execute(
                "INSERT INTO users (username, token_hash, created_at)"
                " VALUES (:username, :token_hash, :created_at)",
                {
                    "username": payload.username,
                    "token_hash": hash_token(token),
                    "created_at": created_at,
                },
            )
    except sqlite3.IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken") from None
    return UserCreated(
        id=cursor.lastrowid, username=payload.username, created_at=created_at, token=token
    )


@router.get("/me")
def me(user: CurrentUser) -> UserOut:
    return UserOut(id=user.id, username=user.username, created_at=user.created_at)
