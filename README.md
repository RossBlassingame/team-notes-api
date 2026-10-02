# Team Notes API

REST backend for notes shared across small teams. Work in progress — see [PLAN.md](PLAN.md) for the design.

## Run

```bash
uv sync
uv run fastapi dev   # http://127.0.0.1:8000/docs
```

## Test

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```
