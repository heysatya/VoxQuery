from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID
from time import perf_counter

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings, get_settings
from app.main import app
from app.middleware import auth
from app.middleware.auth import ClerkJwtVerifier, get_clerk_verifier, get_current_user
from app.models.contracts import ApiError

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
TENANT_ID = UUID("00000000-0000-0000-0000-000000000101")
OTHER_TENANT_ID = UUID("00000000-0000-0000-0000-000000000999")
ISSUER = "https://clerk.voxquery.test"
JWKS_URL = "https://clerk.voxquery.test/.well-known/jwks.json"


class FakeJwksClient:
    def __init__(self, public_key) -> None:
        self.public_key = public_key
        self.calls = 0

    def get_signing_key_from_jwt(self, token: str):
        self.calls += 1
        return SimpleNamespace(key=self.public_key)


@pytest.fixture
def key_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture
def clerk_settings():
    return Settings(
        APP_ENV="test",
        AUTH_MODE="clerk",
        CLERK_ISSUER=ISSUER,
        CLERK_JWKS_URL=JWKS_URL,
    )


def signed_token(private_key, **overrides) -> str:
    payload = {
        "iss": ISSUER,
        "sub": "user_test",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "vox_user_id": str(USER_ID),
        "vox_tenant_id": str(TENANT_ID),
        "email": "local-user@voxquery.test",
        "role": "viewer",
        "snowflake_role": "ANALYST_READONLY",
    }
    payload.update(overrides)
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": "test-key"})


def test_clerk_verifier_accepts_signed_token_and_maps_claims(key_pair, clerk_settings):
    private_key, public_key = key_pair
    verifier = ClerkJwtVerifier(clerk_settings, jwks_client=FakeJwksClient(public_key))

    claims = verifier.verify(signed_token(private_key))

    assert claims.user_id == USER_ID
    assert claims.tenant_id == TENANT_ID
    assert claims.email == "local-user@voxquery.test"
    assert claims.role == "viewer"
    assert claims.snowflake_role == "ANALYST_READONLY"


def test_clerk_verifier_rejects_invalid_issuer(key_pair, clerk_settings):
    private_key, public_key = key_pair
    verifier = ClerkJwtVerifier(clerk_settings, jwks_client=FakeJwksClient(public_key))

    with pytest.raises(ApiError) as exc:
        verifier.verify(signed_token(private_key, iss="https://attacker.example"))

    assert exc.value.code == "auth_invalid"


def test_clerk_verifier_rejects_missing_voxquery_claims(key_pair, clerk_settings):
    private_key, public_key = key_pair
    verifier = ClerkJwtVerifier(clerk_settings, jwks_client=FakeJwksClient(public_key))

    with pytest.raises(ApiError) as exc:
        verifier.verify(signed_token(private_key, vox_tenant_id=None))

    assert exc.value.code == "auth_invalid"
    assert "VoxQuery authorization claims" in exc.value.detail


def test_clerk_startup_requires_metadata_and_https_in_hosted_envs():
    missing = Settings(APP_ENV="test", AUTH_MODE="clerk")
    with pytest.raises(RuntimeError, match="CLERK_ISSUER"):
        missing.validate_startup()

    non_tls = Settings(
        APP_ENV="production",
        AUTH_MODE="clerk",
        CLERK_ISSUER="http://clerk.voxquery.test",
        CLERK_JWKS_URL=JWKS_URL,
    )
    with pytest.raises(RuntimeError, match="https://"):
        non_tls.validate_startup()

    configured = Settings(
        APP_ENV="production",
        AUTH_MODE="clerk",
        CLERK_ISSUER=ISSUER,
        CLERK_JWKS_URL=JWKS_URL,
    )
    configured.validate_startup()


def test_rest_auth_requires_bearer_header_in_clerk_mode(clerk_settings):
    with pytest.raises(ApiError) as missing:
        get_current_user(authorization=None, settings=clerk_settings)
    assert missing.value.code == "auth_missing"

    with pytest.raises(ApiError) as invalid:
        get_current_user(authorization="Token nope", settings=clerk_settings)
    assert invalid.value.code == "auth_invalid"


def test_clerk_verifier_is_cached_per_settings(clerk_settings):
    auth._VERIFIER_CACHE.clear()

    first = get_clerk_verifier(clerk_settings)
    second = get_clerk_verifier(clerk_settings)

    assert first is second
    auth._VERIFIER_CACHE.clear()


def test_rest_session_enforces_clerk_tenant_claims(monkeypatch, key_pair):
    private_key, public_key = key_pair
    verifier = ClerkJwtVerifier(
        Settings(APP_ENV="test", AUTH_MODE="clerk", CLERK_ISSUER=ISSUER, CLERK_JWKS_URL=JWKS_URL),
        jwks_client=FakeJwksClient(public_key),
    )
    restore_settings = force_clerk_mode(monkeypatch, verifier)
    client = TestClient(app)
    token = signed_token(private_key)
    try:
        response = client.post(
            "/api/session",
            headers={"Authorization": f"Bearer {token}"},
            json={"tenant_id": str(TENANT_ID)},
        )
        assert response.status_code == 201

        mismatch = client.post(
            "/api/session",
            headers={"Authorization": f"Bearer {token}"},
            json={"tenant_id": str(OTHER_TENANT_ID)},
        )
        assert mismatch.status_code == 401
        assert mismatch.json()["error"]["code"] == "auth_invalid"
    finally:
        restore_settings()


def test_websocket_auth_accepts_valid_token_and_rejects_missing_token(monkeypatch, key_pair):
    private_key, public_key = key_pair
    verifier = ClerkJwtVerifier(
        Settings(APP_ENV="test", AUTH_MODE="clerk", CLERK_ISSUER=ISSUER, CLERK_JWKS_URL=JWKS_URL),
        jwks_client=FakeJwksClient(public_key),
    )
    restore_settings = force_clerk_mode(monkeypatch, verifier)
    client = TestClient(app)
    token = signed_token(private_key)
    try:
        session = client.post(
            "/api/session",
            headers={"Authorization": f"Bearer {token}"},
            json={"tenant_id": str(TENANT_ID)},
        ).json()

        with client.websocket_connect(
            f"/ws/pipeline?session_id={session['session_id']}&token={token}"
        ) as ws:
            assert ws is not None

        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(f"/ws/pipeline?session_id={session['session_id']}"):
                pass
        assert exc.value.code == 4001
    finally:
        restore_settings()


def test_clerk_verification_stays_within_local_budget(key_pair, clerk_settings):
    private_key, public_key = key_pair
    verifier = ClerkJwtVerifier(clerk_settings, jwks_client=FakeJwksClient(public_key))
    token = signed_token(private_key)

    started = perf_counter()
    for _ in range(25):
        assert verifier.verify(token).tenant_id == TENANT_ID
    elapsed_ms = (perf_counter() - started) * 1000

    assert elapsed_ms < 500


def force_clerk_mode(monkeypatch, verifier: ClerkJwtVerifier):
    settings = get_settings()
    original = {
        "auth_mode": settings.auth_mode,
        "clerk_issuer": settings.clerk_issuer,
        "clerk_jwks_url": settings.clerk_jwks_url,
    }
    settings.auth_mode = "clerk"
    settings.clerk_issuer = ISSUER
    settings.clerk_jwks_url = JWKS_URL
    monkeypatch.setattr(auth, "get_clerk_verifier", lambda current_settings: verifier)

    def restore_settings() -> None:
        settings.auth_mode = original["auth_mode"]
        settings.clerk_issuer = original["clerk_issuer"]
        settings.clerk_jwks_url = original["clerk_jwks_url"]

    return restore_settings
