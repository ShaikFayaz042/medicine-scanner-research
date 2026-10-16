"""Authentication endpoints for the mobile app."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server import deps as server_deps
from server import config as server_config
from server.auth import google_oauth
from server.auth.security import (
    create_access_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from server.database.mobile_models import User
from server.rate_limit import limiter
from server.schemas.auth import AuthResponse, GoogleLoginRequest, LoginRequest, RegisterRequest, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def _web_callback_url(result: str) -> str:
    callback = urlsplit(server_config.GOOGLE_WEB_APP_CALLBACK_URI)
    query = dict(parse_qsl(callback.query, keep_blank_values=True))
    query["google_oauth"] = result
    return urlunsplit((callback.scheme, callback.netloc, callback.path, urlencode(query), ""))


def _oauth_is_configured() -> bool:
    if not all((server_config.GOOGLE_WEB_CLIENT_ID, server_config.GOOGLE_WEB_CLIENT_SECRET)):
        return False
    if not server_config.GOOGLE_WEB_OAUTH_STATE_SECRET or len(server_config.GOOGLE_WEB_OAUTH_STATE_SECRET) < 32:
        return False
    if server_config.GOOGLE_WEB_OAUTH_COOKIE_SAMESITE not in {"lax", "none"}:
        return False

    parsed_urls = []
    for value, required_path in (
        (server_config.GOOGLE_WEB_REDIRECT_URI, "/auth/google/callback"),
        (server_config.GOOGLE_WEB_APP_CALLBACK_URI, "/auth/google"),
    ):
        parsed = urlsplit(value)
        if parsed.path != required_path or parsed.query or parsed.fragment or not parsed.hostname:
            return False
        if server_config.APP_ENV.lower() == "production":
            if parsed.scheme != "https":
                return False
        elif parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            return False
        parsed_urls.append(parsed)

    if server_config.GOOGLE_WEB_OAUTH_COOKIE_SAMESITE == "none":
        if any(parsed.scheme != "https" for parsed in parsed_urls):
            return False
    else:
        if parsed_urls[0].scheme != parsed_urls[1].scheme:
            return False
        if server_config.APP_ENV.lower() != "production" and parsed_urls[0].hostname != parsed_urls[1].hostname:
            return False
    return True


def _set_oauth_cookie(response, name: str, value: str, max_age: int) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,
        secure=urlsplit(server_config.GOOGLE_WEB_REDIRECT_URI).scheme == "https",
        samesite=server_config.GOOGLE_WEB_OAUTH_COOKIE_SAMESITE,
        path="/auth/google",
    )


def _clear_oauth_cookie(response, name: str) -> None:
    response.delete_cookie(
        name,
        httponly=True,
        secure=urlsplit(server_config.GOOGLE_WEB_REDIRECT_URI).scheme == "https",
        samesite=server_config.GOOGLE_WEB_OAUTH_COOKIE_SAMESITE,
        path="/auth/google",
    )


def _browser_redirect(result: str, clear_transaction: bool = False) -> RedirectResponse:
    response = RedirectResponse(_web_callback_url(result), status_code=status.HTTP_303_SEE_OTHER)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    if clear_transaction:
        _clear_oauth_cookie(response, google_oauth.TRANSACTION_COOKIE)
    return response


@router.get("/google/start")
@limiter.limit(server_config.RATE_LIMIT_AUTH)
def google_web_start(request: Request) -> RedirectResponse:
    if not _oauth_is_configured():
        return _browser_redirect("error")

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    transaction = google_oauth.sign_cookie(
        {"iat": int(time.time()), "state": state, "nonce": nonce, "verifier": verifier},
        "transaction",
    )
    parameters = urlencode(
        {
            "client_id": server_config.GOOGLE_WEB_CLIENT_ID,
            "redirect_uri": server_config.GOOGLE_WEB_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    response = RedirectResponse(
        f"{google_oauth.GOOGLE_AUTHORIZATION_ENDPOINT}?{parameters}",
        status_code=status.HTTP_302_FOUND,
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    _set_oauth_cookie(response, google_oauth.TRANSACTION_COOKIE, transaction, google_oauth.TRANSACTION_TTL_SECONDS)
    return response


@router.get("/google/callback")
@limiter.limit(server_config.RATE_LIMIT_AUTH)
def google_web_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(server_deps.get_mobile_db),
) -> RedirectResponse:
    transaction = google_oauth.unsign_cookie(
        request.cookies.get(google_oauth.TRANSACTION_COOKIE),
        "transaction",
        google_oauth.TRANSACTION_TTL_SECONDS,
    )
    if not _oauth_is_configured():
        logger.warning("Google OAuth callback failed: server configuration is invalid")
        return _browser_redirect("error", clear_transaction=True)
    if not transaction:
        logger.warning("Google OAuth callback failed: transaction cookie is missing or invalid")
        return _browser_redirect("error", clear_transaction=True)
    if not state:
        logger.warning("Google OAuth callback failed: state parameter is missing")
        return _browser_redirect("error", clear_transaction=True)
    if not hmac.compare_digest(str(transaction.get("state", "")), state):
        logger.warning("Google OAuth callback failed: state validation failed")
        return _browser_redirect("error", clear_transaction=True)
    if error:
        if error != "access_denied":
            logger.warning("Google OAuth provider returned an authorization error")
        return _browser_redirect("cancelled" if error == "access_denied" else "error", clear_transaction=True)
    if not code or not isinstance(transaction.get("verifier"), str) or not isinstance(transaction.get("nonce"), str):
        logger.warning("Google OAuth callback failed: code or PKCE transaction data is missing")
        return _browser_redirect("error", clear_transaction=True)

    try:
        token_data = google_oauth.exchange_authorization_code(code, transaction["verifier"])
    except (google_oauth.GoogleOAuthError, ValueError, TypeError) as exc:
        logger.warning("Google OAuth authorization-code exchange failed: %s", exc)
        return _browser_redirect("error", clear_transaction=True)
    try:
        claims = google_oauth.verify_google_id_token(token_data["id_token"], transaction["nonce"])
    except (google_oauth.GoogleOAuthError, ValueError, TypeError) as exc:
        logger.warning("Google OAuth ID-token verification failed: %s", exc)
        return _browser_redirect("error", clear_transaction=True)
    email = claims["email"].lower()
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if user is None:
        user = User(id=uuid.uuid4(), name=claims.get("name") or email.split("@")[0], email=email)
        db.add(user)
        try:
            db.commit()
            db.refresh(user)
        except IntegrityError:
            db.rollback()
            user = db.query(User).filter(func.lower(User.email) == email).first()
            if user is None:
                return _browser_redirect("error", clear_transaction=True)

    session = _session_for(user)
    response = _browser_redirect("complete", clear_transaction=True)
    response.set_cookie(
        google_oauth.SESSION_COOKIE,
        google_oauth.sign_cookie(
            {"iat": int(time.time()), "session": session.model_dump(mode="json", by_alias=True)},
            "session",
        ),
        max_age=google_oauth.SESSION_TTL_SECONDS,
        httponly=True,
        secure=urlsplit(server_config.GOOGLE_WEB_REDIRECT_URI).scheme == "https",
        samesite=server_config.GOOGLE_WEB_OAUTH_COOKIE_SAMESITE,
        path="/auth/google",
    )
    return response


@router.post("/google/session", response_model=AuthResponse)
@limiter.limit(server_config.RATE_LIMIT_AUTH)
def consume_google_web_session(request: Request) -> AuthResponse:
    expected = urlsplit(server_config.GOOGLE_WEB_APP_CALLBACK_URI)
    expected_origin = f"{expected.scheme}://{expected.netloc}"
    if request.headers.get("origin") != expected_origin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid sign-in session request.")

    payload = google_oauth.unsign_cookie(
        request.cookies.get(google_oauth.SESSION_COOKIE),
        "session",
        google_oauth.SESSION_TTL_SECONDS,
    )
    if not payload or not isinstance(payload.get("session"), dict):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google sign-in session expired. Please try again.")

    response = JSONResponse(content=AuthResponse.model_validate(payload["session"]).model_dump(mode="json", by_alias=True))
    _clear_oauth_cookie(response, google_oauth.SESSION_COOKIE)
    response.headers["Cache-Control"] = "no-store"
    return response


def _session_for(user: User) -> AuthResponse:
    token, expires_in = create_access_token(user.id)
    return AuthResponse(token=token, expires_in=expires_in, user=UserOut.model_validate(user))


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(server_config.RATE_LIMIT_AUTH)
def register(request: Request, body: RegisterRequest, db: Session = Depends(server_deps.get_mobile_db)) -> AuthResponse:
    email = body.email.lower()
    existing = db.query(User).filter(func.lower(User.email) == email).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with that email already exists.")

    user = User(id=uuid.uuid4(), name=body.name, email=email, password_hash=hash_password(body.password))
    response = _session_for(user)
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with that email already exists.") from None

    return response


@router.post("/login", response_model=AuthResponse)
@limiter.limit(server_config.RATE_LIMIT_AUTH)
def login(request: Request, body: LoginRequest, db: Session = Depends(server_deps.get_mobile_db)) -> AuthResponse:
    email = body.email.lower()
    user = db.query(User).filter(func.lower(User.email) == email).first()

    if user is None or not user.password_hash:
        hash_password(body.password)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password.")

    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password.")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
        db.commit()

    return _session_for(user)


@router.post("/google", response_model=AuthResponse)
@limiter.limit(server_config.RATE_LIMIT_AUTH)
def google_login(request: Request, body: GoogleLoginRequest, db: Session = Depends(server_deps.get_mobile_db)) -> AuthResponse:
    if not server_config.GOOGLE_WEB_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Google sign-in is not configured on this server.",
        )

    try:
        claims = google_oauth.verify_google_id_token(
            body.id_token,
            audiences=(server_config.GOOGLE_WEB_CLIENT_ID,),
        )
    except google_oauth.GoogleUnverifiedEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="That Google account has no verified email address.",
        ) from exc
    except google_oauth.GoogleOAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not verify that Google account.") from exc

    email = str(claims["email"]).lower()
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if user is None:
        user = User(id=uuid.uuid4(), name=claims.get("name") or email.split("@")[0], email=email)
        response = _session_for(user)
        db.add(user)
        try:
            db.commit()
            db.refresh(user)
        except IntegrityError:
            db.rollback()
            user = db.query(User).filter(func.lower(User.email) == email).first()
            if user is None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Unable to create Google user account.")
            return _session_for(user)
        return response

    return _session_for(user)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(server_deps.get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)
