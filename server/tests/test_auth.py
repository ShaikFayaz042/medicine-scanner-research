import time
import uuid
import base64
import hashlib
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

import server.auth.security as auth_security
import server.auth.google_oauth as google_oauth
import server.deps as deps_module
import server.routes.auth as auth_route
from server.auth.errors import register_auth_error_handlers
from server import config as server_config
from server.database.mobile_models import User
from server.rate_limit import limiter


class FakeQuery:
    def __init__(self, session, model):
        self.session = session
        self.model = model
        self._filters = []

    def filter(self, criterion):
        self._filters.append(criterion)
        return self

    def first(self):
        for record in self.session._records_for_model(self.model):
            if all(self._matches(record, criterion) for criterion in self._filters):
                return record
        return None

    def _matches(self, record, criterion):
        if criterion is None:
            return True
        left = str(getattr(criterion, "left", "")).lower()
        right = getattr(getattr(criterion, "right", None), "value", getattr(criterion, "right", None))
        right_text = str(right).lower()

        if "lower" in left and "email" in left:
            return record.email.lower() == right_text
        if "users.id" in left or "id" in left:
            return str(record.id) == str(right)
        return True


class FakeSession:
    def __init__(self):
        self.users = []
        self.close_count = 0
        self.commit_count = 0

    def _records_for_model(self, model):
        if model is User:
            return self.users
        return []

    def query(self, model):
        return FakeQuery(self, model)

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.users.append(obj)

    def commit(self):
        self.commit_count += 1

    def refresh(self, obj):
        pass

    def rollback(self):
        pass

    def close(self):
        self.close_count += 1


def build_client(monkeypatch):
    fake_session = FakeSession()

    def override_get_mobile_db():
        try:
            yield fake_session
        finally:
            fake_session.close()

    def override_get_current_user(credentials=None, db=None):
        if credentials is None or not getattr(credentials, "credentials", None):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
        token = credentials.credentials
        try:
            user_id = auth_security.decode_access_token(token)
        except Exception as exc:  # pragma: no cover - exercised through the route contract
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your session has expired. Please sign in again.") from exc
        for user in fake_session.users:
            if user.id == user_id:
                return user
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account no longer exists.")

    monkeypatch.setattr(auth_security, "JWT_SECRET_KEY", "0123456789abcdef0123456789abcdef")
    monkeypatch.setattr(auth_security, "JWT_ALGORITHM", "HS256")
    monkeypatch.setattr(auth_security, "ACCESS_TOKEN_TTL_MINUTES", 60)
    monkeypatch.setattr(server_config, "GOOGLE_WEB_CLIENT_ID", None)
    monkeypatch.setattr(server_config, "GOOGLE_ANDROID_CLIENT_ID", None)
    monkeypatch.setattr(server_config, "GOOGLE_IOS_CLIENT_ID", None)
    monkeypatch.setattr(server_config, "GOOGLE_WEB_CLIENT_SECRET", None)
    monkeypatch.setattr(server_config, "GOOGLE_WEB_OAUTH_STATE_SECRET", None)
    monkeypatch.setattr(server_config, "GOOGLE_WEB_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
    monkeypatch.setattr(server_config, "GOOGLE_WEB_APP_CALLBACK_URI", "http://localhost:8081/auth/google")
    monkeypatch.setattr(server_config, "GOOGLE_WEB_OAUTH_COOKIE_SAMESITE", "lax")
    monkeypatch.setattr(server_config, "APP_ENV", "development")
    limiter.reset()

    app = FastAPI()
    app.state.limiter = limiter
    register_auth_error_handlers(app)
    app.dependency_overrides[deps_module.get_mobile_db] = override_get_mobile_db
    app.include_router(auth_route.router)
    return TestClient(app, raise_server_exceptions=False), fake_session


def test_register_returns_token_and_user(monkeypatch):
    client, db = build_client(monkeypatch)

    response = client.post(
        "/auth/register",
        json={"name": "Jo", "email": "jo@example.com", "password": "correct-horse"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["token"]
    assert payload["expiresIn"] > 0
    assert payload["user"]["email"] == "jo@example.com"
    assert "password" not in response.text.lower()
    assert len(db.users) == 1
    assert db.users[0].password_hash != "correct-horse"
    assert db.close_count == 1


def test_registration_validation_uses_mobile_error_contract(monkeypatch):
    client, _ = build_client(monkeypatch)

    response = client.post(
        "/auth/register",
        json={"name": "Jo", "email": "not-an-email", "password": "short"},
        headers={"X-Request-ID": "client-request-123"},
    )

    assert response.status_code == 422
    assert response.json()["requestId"] == "client-request-123"
    assert response.headers["X-Request-ID"] == "client-request-123"
    assert response.json()["detail"].startswith("Invalid request. ")


def test_duplicate_email_is_a_conflict(monkeypatch):
    client, _ = build_client(monkeypatch)
    payload = {"name": "Jo", "email": "dup@example.com", "password": "correct-horse"}

    first = client.post("/auth/register", json=payload)
    second = client.post("/auth/register", json=payload)

    assert first.status_code == 201
    assert second.status_code == 409
    assert "already exists" in second.json()["detail"].lower()


def test_login_success_and_failure(monkeypatch):
    client, _ = build_client(monkeypatch)
    client.post(
        "/auth/register",
        json={"name": "Jo", "email": "real@example.com", "password": "correct-horse"},
    )

    success = client.post(
        "/auth/login",
        json={"email": "real@example.com", "password": "correct-horse"},
    )
    wrong = client.post(
        "/auth/login",
        json={"email": "real@example.com", "password": "wrong-password"},
    )
    missing = client.post(
        "/auth/login",
        json={"email": "ghost@example.com", "password": "wrong-password"},
    )

    assert success.status_code == 200
    assert success.json()["token"]
    assert wrong.status_code == 401
    assert missing.status_code == 401
    assert wrong.json()["detail"] == missing.json()["detail"]


def test_jwt_validation_and_protected_route(monkeypatch):
    client, db = build_client(monkeypatch)
    user = User(
        id=uuid.uuid4(),
        name="Protected User",
        email="me@example.com",
        password_hash=auth_security.hash_password("correct-horse"),
    )
    db.users.append(user)

    token, _ = auth_security.create_access_token(user.id)

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "me@example.com"

    denied = client.get("/auth/me")
    assert denied.status_code == 401

    bad = client.get("/auth/me", headers={"Authorization": "Bearer invalid-token"})
    assert bad.status_code == 401

    now = int(time.time())
    expired_token = jwt.encode(
        {"sub": str(user.id), "iat": now - 120, "exp": now - 60, "typ": "access"},
        auth_security.JWT_SECRET_KEY,
        algorithm="HS256",
    )
    expired = client.get("/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert expired.status_code == 401

    tampered_token = token[:-1] + ("a" if token[-1] != "a" else "b")
    tampered = client.get("/auth/me", headers={"Authorization": f"Bearer {tampered_token}"})
    assert tampered.status_code == 401


def test_invalid_jwt_configuration_fails_closed(monkeypatch):
    user_id = uuid.uuid4()

    monkeypatch.setattr(auth_security, "JWT_SECRET_KEY", None)
    with pytest.raises(RuntimeError, match="not configured"):
        auth_security.create_access_token(user_id)

    monkeypatch.setattr(auth_security, "JWT_SECRET_KEY", "too-short")
    with pytest.raises(ValueError, match="32 characters"):
        auth_security.create_access_token(user_id)

    monkeypatch.setattr(auth_security, "JWT_SECRET_KEY", "0123456789abcdef0123456789abcdef")
    monkeypatch.setattr(auth_security, "JWT_ALGORITHM", "none")
    with pytest.raises(ValueError, match="JWT_ALGORITHM"):
        auth_security.create_access_token(user_id)

    monkeypatch.setattr(auth_security, "JWT_ALGORITHM", None)
    with pytest.raises(ValueError, match="JWT_ALGORITHM"):
        auth_security.create_access_token(user_id)


def test_registration_does_not_persist_if_token_creation_fails(monkeypatch):
    client, db = build_client(monkeypatch)

    def fail_token_creation(user_id):
        raise RuntimeError("token configuration unavailable")

    monkeypatch.setattr(auth_route, "create_access_token", fail_token_creation)
    response = client.post(
        "/auth/register",
        json={"name": "Jo", "email": "rollback@example.com", "password": "correct-horse"},
    )

    assert response.status_code == 500
    assert "requestId" in response.json()
    assert db.users == []
    assert db.commit_count == 0


def _configure_google_verification(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    monkeypatch.setattr(server_config, "GOOGLE_WEB_CLIENT_ID", "test-google-web-client-id")
    monkeypatch.setattr(server_config, "GOOGLE_ANDROID_CLIENT_ID", "test-google-android-client-id")

    class LocalJWKClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_signing_key_from_jwt(self, token):
            return SimpleNamespace(key=public_key)

    monkeypatch.setattr(jwt, "PyJWKClient", LocalJWKClient)
    return private_key


def _configure_google_web_oauth(monkeypatch):
    monkeypatch.setattr(server_config, "GOOGLE_WEB_CLIENT_ID", "test-google-web-client-id")
    monkeypatch.setattr(server_config, "GOOGLE_WEB_CLIENT_SECRET", "test-google-client-secret")
    monkeypatch.setattr(server_config, "GOOGLE_WEB_OAUTH_STATE_SECRET", "test-oauth-state-secret-0123456789abcdef")


def _oauth_start(client):
    response = client.get("/auth/google/start", follow_redirects=False)
    assert response.status_code == 302
    authorization = urlparse(response.headers["location"])
    params = parse_qs(authorization.query)
    return response, params


def test_google_web_start_uses_web_client_code_pkce_and_signed_state(monkeypatch):
    client, _ = build_client(monkeypatch)
    _configure_google_web_oauth(monkeypatch)

    response, params = _oauth_start(client)

    assert params["client_id"] == ["test-google-web-client-id"]
    assert params["redirect_uri"] == ["http://localhost:8000/auth/google/callback"]
    assert params["response_type"] == ["code"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["scope"] == ["openid email profile"]
    transaction = google_oauth.unsign_cookie(
        response.cookies.get(google_oauth.TRANSACTION_COOKIE), "transaction", 600
    )
    assert transaction is not None
    assert transaction["state"] == params["state"][0]
    assert transaction["nonce"] == params["nonce"][0]
    assert transaction["verifier"]
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie


def test_google_web_callback_rejects_invalid_state(monkeypatch):
    client, db = build_client(monkeypatch)
    _configure_google_web_oauth(monkeypatch)
    _, params = _oauth_start(client)

    response = client.get(
        "/auth/google/callback",
        params={"code": "credential-free-test-code", "state": "attacker-state"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "google_oauth=error" in response.headers["location"]
    assert db.users == []


def test_google_web_callback_handles_user_cancellation(monkeypatch):
    client, db = build_client(monkeypatch)
    _configure_google_web_oauth(monkeypatch)
    _, params = _oauth_start(client)

    response = client.get(
        "/auth/google/callback",
        params={"error": "access_denied", "state": params["state"][0]},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "google_oauth=cancelled" in response.headers["location"]
    assert db.users == []


def test_google_web_start_rejects_mismatched_local_cookie_hosts(monkeypatch):
    client, _ = build_client(monkeypatch)
    _configure_google_web_oauth(monkeypatch)
    monkeypatch.setattr(
        server_config,
        "GOOGLE_WEB_REDIRECT_URI",
        "http://127.0.0.1:8000/auth/google/callback",
    )

    response = client.get("/auth/google/start", follow_redirects=False)

    assert response.status_code == 303
    assert "google_oauth=error" in response.headers["location"]


def test_google_web_callback_handles_token_exchange_failure(monkeypatch):
    client, db = build_client(monkeypatch)
    _configure_google_web_oauth(monkeypatch)
    _, params = _oauth_start(client)

    def fail_exchange(*args, **kwargs):
        raise google_oauth.GoogleOAuthError("provider unavailable")

    monkeypatch.setattr(google_oauth, "exchange_authorization_code", fail_exchange)
    response = client.get(
        "/auth/google/callback",
        params={"code": "credential-free-test-code", "state": params["state"][0]},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "google_oauth=error" in response.headers["location"]
    assert "credential-free-test-code" not in response.headers["location"]
    assert db.users == []


def test_google_web_code_exchange_validates_nonce_and_returns_existing_session(monkeypatch):
    client, db = build_client(monkeypatch)
    _configure_google_web_oauth(monkeypatch)
    private_key = _configure_google_verification(monkeypatch)
    start_response, params = _oauth_start(client)
    transaction = google_oauth.unsign_cookie(
        start_response.cookies.get(google_oauth.TRANSACTION_COOKIE), "transaction", 600
    )
    assert transaction is not None
    expected_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(transaction["verifier"].encode()).digest()
    ).rstrip(b"=").decode()
    assert params["code_challenge"] == [expected_challenge]

    sent = {}

    class TokenResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "id_token": _google_token(
                    private_key,
                    aud="test-google-web-client-id",
                    nonce=transaction["nonce"],
                )
            }

    def fake_post(url, data, timeout):
        sent.update({"url": url, **data, "timeout": timeout})
        return TokenResponse()

    monkeypatch.setattr(google_oauth.requests, "post", fake_post)
    callback = client.get(
        "/auth/google/callback",
        params={"code": "credential-free-test-code", "state": params["state"][0]},
        follow_redirects=False,
    )

    assert callback.status_code == 303
    assert "google_oauth=complete" in callback.headers["location"]
    assert sent["url"] == google_oauth.GOOGLE_TOKEN_ENDPOINT
    assert sent["code"] == "credential-free-test-code"
    assert sent["code_verifier"] == transaction["verifier"]
    assert sent["client_secret"] == "test-google-client-secret"
    assert sent["redirect_uri"] == "http://localhost:8000/auth/google/callback"
    assert len(db.users) == 1

    exchanged = client.post(
        "/auth/google/session",
        headers={"Origin": "http://localhost:8081"},
    )
    assert exchanged.status_code == 200
    assert exchanged.json()["token"]
    assert exchanged.json()["user"]["email"] == "google@example.com"
    assert 'medicheck_google_session="";' in exchanged.headers["set-cookie"]


def test_google_web_session_handoff_rejects_wrong_origin(monkeypatch):
    client, _ = build_client(monkeypatch)
    _configure_google_web_oauth(monkeypatch)

    response = client.post(
        "/auth/google/session",
        headers={"Origin": "https://attacker.example"},
    )

    assert response.status_code == 403


def test_google_web_id_token_rejects_wrong_nonce(monkeypatch):
    private_key = _configure_google_verification(monkeypatch)
    token = _google_token(private_key, aud="test-google-web-client-id", nonce="actual-nonce")

    claims = google_oauth.verify_google_id_token(token, "actual-nonce")

    assert claims["sub"] == "google-user-123"
    with pytest.raises(google_oauth.GoogleOAuthError):
        google_oauth.verify_google_id_token(token, "different-nonce")


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "another-client-id"},
        {"iss": "https://attacker.example"},
        {"exp": int(time.time()) - 60, "iat": int(time.time()) - 120},
    ],
    ids=["wrong-audience", "wrong-issuer", "expired"],
)
def test_google_web_id_token_rejects_invalid_claims(monkeypatch, overrides):
    private_key = _configure_google_verification(monkeypatch)
    token = _google_token(private_key, nonce="expected-nonce", **overrides)

    with pytest.raises(google_oauth.GoogleOAuthError):
        google_oauth.verify_google_id_token(token, "expected-nonce")


def _google_token(private_key, **claim_overrides):
    now = int(time.time())
    claims = {
        "sub": "google-user-123",
        "email": "google@example.com",
        "email_verified": True,
        "name": "Google User",
        "iat": now,
        "exp": now + 300,
        "aud": "test-google-web-client-id",
        "iss": "https://accounts.google.com",
    }
    claims.update(claim_overrides)
    return jwt.encode(claims, private_key, algorithm="RS256")


def test_google_signin_requires_configuration(monkeypatch):
    client, _ = build_client(monkeypatch)
    response = client.post("/auth/google", json={"idToken": "not-a-token"})
    assert response.status_code == 501
    assert "requestId" in response.json()


def test_google_signin_uses_real_signature_and_claim_validation(monkeypatch):
    client, db = build_client(monkeypatch)
    private_key = _configure_google_verification(monkeypatch)
    valid_token = _google_token(private_key)

    response = client.post("/auth/google", json={"idToken": valid_token})
    assert response.status_code == 200
    assert response.json()["user"]["email"] == "google@example.com"
    assert response.json()["token"]
    assert len(db.users) == 1


@pytest.mark.parametrize(
    "overrides,wrong_signing_key",
    [
        ({"aud": "another-client-id"}, False),
        ({"iss": "https://attacker.example"}, False),
        ({"exp": int(time.time()) - 60, "iat": int(time.time()) - 120}, False),
        ({}, True),
    ],
    ids=["wrong-audience", "wrong-issuer", "expired", "invalid-signature"],
)
def test_google_signin_rejects_invalid_tokens(monkeypatch, overrides, wrong_signing_key):
    client, db = build_client(monkeypatch)
    private_key = _configure_google_verification(monkeypatch)
    signing_key = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        if wrong_signing_key
        else private_key
    )
    token = _google_token(signing_key, **overrides)

    response = client.post("/auth/google", json={"idToken": token})
    assert response.status_code == 401
    assert "requestId" in response.json()
    assert db.users == []


def test_google_signin_rejects_unverified_email(monkeypatch):
    client, db = build_client(monkeypatch)
    private_key = _configure_google_verification(monkeypatch)

    response = client.post(
        "/auth/google",
        json={"idToken": _google_token(private_key, email_verified=False)},
    )

    assert response.status_code == 401
    assert "verified email" in response.json()["detail"]
    assert db.users == []


def test_google_signin_rejects_android_client_audience(monkeypatch):
    client, db = build_client(monkeypatch)
    private_key = _configure_google_verification(monkeypatch)
    token = _google_token(private_key, aud="test-google-android-client-id")

    response = client.post("/auth/google", json={"idToken": token})

    assert response.status_code == 401
    assert db.users == []


def test_auth_rate_limit_returns_mobile_error_contract(monkeypatch):
    client, _ = build_client(monkeypatch)
    responses = [
        client.post("/auth/login", json={"email": "nobody@example.com", "password": "nope"})
        for _ in range(11)
    ]

    limited = responses[-1]
    assert limited.status_code == 429
    assert "requestId" in limited.json()
