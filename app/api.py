import os
from pathlib import Path

from fastapi import FastAPI

from app.db import init_schema
from app.routes import notes, teams, users


def create_app(db_path: str | Path | None = None) -> FastAPI:
    db_path = str(db_path or os.environ.get("NOTES_DB_PATH", "notes.db"))
    # Create the schema now rather than in a lifespan hook, so the app is usable whether or
    # not a TestClient is entered as a context manager.
    init_schema(db_path)

    app = FastAPI(title="Team Notes API", version="0.1.0")
    app.state.db_path = db_path
    app.include_router(users.router)
    app.include_router(notes.router)
    app.include_router(teams.router)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
