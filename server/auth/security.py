"""Password hashing and JWT issuing/verification for the mobile app."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from server.config import ACCESS_TOKEN_TTL_MINUTES, JWT_ALGORITHM, JWT_SECRET_KEY

_ALLOWED_JWT_ALGORITHMS = {"HS256", "HS384", "HS512"}
_hasher = PasswordHasher()


class TokenError(Exception):
    """Raised when a bearer token is missing, malformed, expired, or invalid."""


def _require_secret() -> str:
    if not JWT_SECRET_KEY:
        raise RuntimeError("JWT secret is not configured. Set JWT_SECRET_KEY or SECRET_KEY before enabling auth.")
    if len(JWT_SECRET_KEY) < 32:
        raise ValueError("JWT_SECRET_KEY must be at least 32 characters long.")
    return JWT_SECRET_KEY


def _validate_algorithm() -> str:
    algorithm = JWT_ALGORITHM
    if not algorithm or algorithm not in _ALLOWED_JWT_ALGORITHMS:
        raise ValueError(f"JWT_ALGORITHM must be one of {sorted(_ALLOWED_JWT_ALGORITHMS)}.")
    return algorithm


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return False


def create_access_token(user_id: uuid.UUID) -> tuple[str, int]:
    secret = _require_secret()
    algorithm = _validate_algorithm()
    if ACCESS_TOKEN_TTL_MINUTES <= 0:
        raise ValueError("ACCESS_TOKEN_TTL_MINUTES must be greater than zero.")
    now = datetime.now(timezone.utc)
    ttl_seconds = int(ACCESS_TOKEN_TTL_MINUTES * 60)
    expires = now + timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": str(uuid.uuid4()),
        "typ": "access",
    }
    token = jwt.encode(payload, secret, algorithm=algorithm)
    return token, ttl_seconds


def decode_access_token(token: str) -> uuid.UUID:
    secret = _require_secret()
    algorithm = _validate_algorithm()
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[algorithm],
            options={"require": ["exp", "sub", "iat"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc

    if payload.get("typ") != "access":
        raise TokenError("Not an access token.")

    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise TokenError("Token subject is not a valid user id.") from exc
