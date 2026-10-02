import hashlib
import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db import Conn

# Rejects a missing or non-Bearer Authorization header with 401 + WWW-Authenticate.
bearer = HTTPBearer()


@dataclass(frozen=True)
class User:
    id: int
    username: str
    created_at: str


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    # A fast hash is fine for 256-bit random tokens; passwords would need a slow KDF.
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)], conn: Conn
) -> User:
    row = conn.execute(
        "SELECT id, username, created_at FROM users WHERE token_hash = :token_hash",
        {"token_hash": hash_token(credentials.credentials)},
    ).fetchone()
    if row is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return User(**row)


CurrentUser = Annotated[User, Depends(current_user)]
