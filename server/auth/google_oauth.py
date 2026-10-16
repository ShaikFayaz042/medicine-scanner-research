"""Google OAuth code exchange and signed short-lived browser cookies."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

import jwt
import requests

from server import config as server_config

GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_ENDPOINT = "https://www.googleapis.com/oauth2/v3/certs"
TRANSACTION_COOKIE = "medicheck_google_oauth"
SESSION_COOKIE = "medicheck_google_session"
TRANSACTION_TTL_SECONDS = 600
SESSION_TTL_SECONDS = 60


class GoogleOAuthError(Exception):
    """An OAuth response could not be safely completed."""


class GoogleUnverifiedEmailError(GoogleOAuthError):
    """The Google account does not have a verified email address."""


def _cookie_key(purpose: str) -> bytes:
    secret = server_config.GOOGLE_WEB_OAUTH_STATE_SECRET
    if not secret or len(secret) < 32:
        raise GoogleOAuthError("Google OAuth state signing is not configured.")
    return hmac.new(secret.encode(), f"medicheck:{purpose}".encode(), hashlib.sha256).digest()


def sign_cookie(payload: dict[str, Any], purpose: str) -> str:
    body = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).rstrip(b"=")
    signature = hmac.new(_cookie_key(purpose), body, hashlib.sha256).digest()
    return f"{body.decode()}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def unsign_cookie(value: str | None, purpose: str, max_age: int) -> dict[str, Any] | None:
    if not value or len(value) > 8192:
        return None
    try:
        body, supplied_signature = value.split(".", 1)
        expected_signature = hmac.new(
            _cookie_key(purpose), body.encode(), hashlib.sha256
        ).digest()
        signature = base64.urlsafe_b64decode(supplied_signature + "=" * (-len(supplied_signature) % 4))
        if not hmac.compare_digest(signature, expected_signature):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if not isinstance(payload, dict):
            return None
        issued_at = payload.get("iat")
        if not isinstance(issued_at, int) or issued_at > time.time() or time.time() - issued_at > max_age:
            return None
        return payload
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError, GoogleOAuthError):
        return None


def exchange_authorization_code(code: str, code_verifier: str) -> dict[str, Any]:
    try:
        response = requests.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": server_config.GOOGLE_WEB_CLIENT_ID,
                "client_secret": server_config.GOOGLE_WEB_CLIENT_SECRET,
                "redirect_uri": server_config.GOOGLE_WEB_REDIRECT_URI,
                "code_verifier": code_verifier,
            },
            timeout=10,
        )
        response.raise_for_status()
        token_data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise GoogleOAuthError("Google could not complete the sign-in request.") from exc
    if not isinstance(token_data, dict) or not isinstance(token_data.get("id_token"), str):
        raise GoogleOAuthError("Google did not return an ID token.")
    return token_data


def verify_google_id_token(
    id_token: str,
    expected_nonce: str | None = None,
    audiences: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    expected_audiences = audiences or (
        (server_config.GOOGLE_WEB_CLIENT_ID,)
        if server_config.GOOGLE_WEB_CLIENT_ID
        else ()
    )
    if not expected_audiences:
        raise GoogleOAuthError("Google ID token audience is not configured.")

    try:
        jwks_client = jwt.PyJWKClient(GOOGLE_JWKS_ENDPOINT, cache_keys=True, timeout=10)
        signing_key = jwks_client.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=expected_audiences,
            issuer=["https://accounts.google.com", "accounts.google.com"],
            options={"require": ["exp", "iat", "aud", "iss", "sub"]},
        )
    except Exception as exc:
        raise GoogleOAuthError(
            f"Could not verify the Google account ({type(exc).__name__}: {exc})."
        ) from exc

    if claims.get("aud") not in expected_audiences:
        raise GoogleOAuthError("Google ID token audience claim did not match a configured client ID.")
    if expected_nonce is not None and not hmac.compare_digest(
        str(claims.get("nonce", "")), expected_nonce
    ):
        raise GoogleOAuthError("Google ID token nonce did not match the sign-in transaction.")
    if claims.get("email_verified") is not True or not isinstance(claims.get("email"), str):
        raise GoogleUnverifiedEmailError("The Google account does not have a verified email address.")
    return claims