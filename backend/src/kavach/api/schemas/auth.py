"""Authentication DTOs (API.md "Authentication formats")."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints


class LoginRequest(BaseModel):
    # Over-length input is rejected, never truncated; the password never appears in errors/repr.
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    username: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=80)]
    password: Annotated[SecretStr, Field(min_length=1, max_length=256)]


class SessionUser(BaseModel):
    id: UUID
    display_name: str
    role: Literal["viewer", "analyst", "admin"]


class SessionData(BaseModel):
    user: SessionUser
    # The earlier of the idle and absolute deadlines.
    expires_at: datetime
    csrf_token: str


class SessionResponse(BaseModel):
    data: SessionData
    request_id: UUID
