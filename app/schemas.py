from typing import Annotated

from fastapi import Path
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

# SQLite integers are 64-bit; anything larger would overflow in the driver and 500.
MAX_INT = 2**63 - 1
RowId = Annotated[int, Path(ge=1, le=MAX_INT)]


# Must start with a letter or digit, so a username is always a safe URL path segment
# (no "." or "..").
USERNAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
Username = Annotated[str, Field(min_length=1, max_length=32, pattern=USERNAME_PATTERN)]
UsernamePath = Annotated[str, Path(min_length=1, max_length=32, pattern=USERNAME_PATTERN)]


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


class NoteUpdate(Input):
    """Partial update: send only the fields to change. `null` is not a valid value."""

    title: Title | None = None
    body: Body | None = None

    @model_validator(mode="after")
    def require_non_null_changes(self) -> "NoteUpdate":
        if not self.model_fields_set:
            raise ValueError("Provide at least one of: title, body")
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class NoteOut(BaseModel):
    id: int
    owner_id: int
    title: str
    body: str
    version: int
    created_at: str
    updated_at: str
    shared_with: list[int] = Field(description="Ids of the teams this note is shared with")


class NoteList(BaseModel):
    items: list[NoteOut]
    limit: int
    offset: int


TeamName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class TeamCreate(Input):
    name: TeamName


class MemberAdd(Input):
    username: Username


class TeamOut(BaseModel):
    id: int
    name: str
    created_by: int
    created_at: str


class TeamList(BaseModel):
    items: list[TeamOut]
