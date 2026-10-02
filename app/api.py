import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

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

    @app.exception_handler(RequestValidationError)
    def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default 422 echoes the rejected input back. That can be megabytes, or
        # text that can't even be encoded as UTF-8 (a lone surrogate turned it into a 500).
        errors = [{k: v for k, v in error.items() if k != "input"} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
