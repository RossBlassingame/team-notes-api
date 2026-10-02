import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

SCHEMA = (Path(__file__).parent / "schema.sql").read_text()


def connect(db_path: str) -> sqlite3.Connection:
    # One connection per request. FastAPI may run a sync dependency and the endpoint on
    # different threadpool threads, so the same-thread check has to be off.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_schema(db_path: str) -> None:
    conn = connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
    finally:
        conn.close()


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    # Only closes. FastAPI runs code after `yield` once the response has been sent, so
    # committing here could fail silently. Writes commit in `with conn:` blocks instead.
    conn = connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")
