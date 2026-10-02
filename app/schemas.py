from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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
