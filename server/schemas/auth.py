"""Schemas for the mobile authentication endpoints."""

from uuid import UUID

from pydantic import EmailStr, Field, field_validator

from server.schemas.common import CamelModel

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


class LoginRequest(CamelModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class RegisterRequest(CamelModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("password")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Password cannot be only whitespace.")
        return value


class GoogleLoginRequest(CamelModel):
    id_token: str = Field(min_length=1, max_length=4096)


class UserOut(CamelModel):
    id: UUID
    name: str
    email: EmailStr


class AuthResponse(CamelModel):
    token: str
    expires_in: int
    user: UserOut
