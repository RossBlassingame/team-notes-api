"""ASGI entrypoint: `uv run fastapi dev` serves `app` from this module."""

from app.api import create_app

app = create_app()
