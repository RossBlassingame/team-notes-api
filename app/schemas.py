from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Username = Annotated[str, Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")]


class Input(BaseModel):
    """Request bodies reject unknown fields instead of silently ignoring them."""

    model_config = ConfigDict(extra="forbid")


class UserCreate(Input):
    username: Username


class UserOut(BaseModel):
    id: int
    username: str
    created_at: str


class UserCreated(UserOut):
    token: str = Field(description="Bearer token. Shown once; only its hash is stored.")


Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Body = Annotated[str, Field(max_length=100_000)]


class NoteCreate(Input):
    title: Title
    body: Body = ""


class NoteOut(BaseModel):
    id: int
    owner_id: int
    title: str
    body: str
    version: int
    created_at: str
    updated_at: str


class NoteList(BaseModel):
    items: list[NoteOut]
