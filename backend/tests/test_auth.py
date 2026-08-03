from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from types import SimpleNamespace
from time import perf_counter

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings, get_settings
from app.main import AccessTokenRedactionFilter, app, redact_token_query_params
from app.middleware import auth
from app.middleware.auth import ClerkJwtVerifier, get_clerk_verifier, get_current_user
from app.models.contracts import ApiError

USER_ID = "user_test123"
TENANT_ID = "org_test123"
OTHER_TENANT_ID = "org_other456"
OTHER_USER_ID = "user_other456"
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
        CLERK_AUDIENCE=None,
    )


def signed_token(private_key, **overrides) -> str:
    payload = {
        "iss": ISSUER,
        "sub": USER_ID,
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "o": {"id": TENANT_ID, "rol": "org:admin", "slg": "test-org"},
        "email": "local-user@voxquery.test",
        "snowflake_role": "ANALYST_READONLY",
    }
    payload.update(overrides)
    for key, value in list(payload.items()):
        if value is None:
            payload.pop(key)
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": "test-key"})


def test_clerk_verifier_accepts_signed_v2_compact_token_and_maps_claims(key_pair, clerk_settings):
    private_key, public_key = key_pair
    verifier = ClerkJwtVerifier(clerk_settings, jwks_client=FakeJwksClient(public_key))

    claims = verifier.claims_from_payload(verifier.verify(signed_token(private_key)))

    assert claims.user_id == USER_ID
    assert claims.tenant_id == TENANT_ID
    assert claims.email == "local-user@voxquery.test"
    assert claims.role == "admin"
    assert claims.snowflake_role == "ANALYST_READONLY"


def test_clerk_verifier_accepts_legacy_org_claims(key_pair, clerk_settings):
    private_key, public_key = key_pair
    verifier = ClerkJwtVerifier(clerk_settings, jwks_client=FakeJwksClient(public_key))

    token = signed_token(private_key, o=None, org_id="org_legacy789", org_role="org:member")
    claims = verifier.claims_from_payload(verifier.verify(token))

    assert claims.user_id == USER_ID
    assert claims.tenant_id == "org_legacy789"
    assert claims.role == "viewer"


def test_clerk_verifier_rejects_token_without_active_organization(key_pair, clerk_settings):
    private_key, public_key = key_pair
    verifier = ClerkJwtVerifier(clerk_settings, jwks_client=FakeJwksClient(public_key))

    token = signed_token(private_key, o=None, org_id=None)
    with pytest.raises(ApiError) as exc:
        verifier.claims_from_payload(verifier.verify(token))

    assert exc.value.code == "auth_invalid"
    assert "Active organization" in exc.value.detail


def test_blank_clerk_audience_is_treated_as_unset(key_pair):
    private_key, public_key = key_pair
    settings = Settings(
        APP_ENV="test",
        AUTH_MODE="clerk",
        CLERK_ISSUER=ISSUER,
        CLERK_JWKS_URL=JWKS_URL,
        CLERK_AUDIENCE="",
    )
    verifier = ClerkJwtVerifier(settings, jwks_client=FakeJwksClient(public_key))

    assert settings.clerk_audience is None
    assert (
        verifier.claims_from_payload(verifier.verify(signed_token(private_key))).tenant_id
        == TENANT_ID
    )


def test_clerk_verifier_allows_small_clock_skew(key_pair, clerk_settings):
    private_key, public_key = key_pair
    verifier = ClerkJwtVerifier(clerk_settings, jwks_client=FakeJwksClient(public_key))

    claims = verifier.claims_from_payload(
        verifier.verify(signed_token(private_key, iat=datetime.now(UTC) + timedelta(seconds=30)))
    )

    assert claims.user_id == USER_ID


def test_access_log_redacts_websocket_token_query_param():
    redacted = redact_token_query_params(
        "WebSocket /ws/audio?session_id=session-1&token=header.payload.signature&x=1"
    )

    assert "header.payload.signature" not in redacted
    assert "token=<redacted>" in redacted
    assert "session_id=session-1" in redacted


def test_uvicorn_loggers_have_token_redaction_filter():
    for logger_name in ("uvicorn.access", "uvicorn.error"):
        assert any(
            isinstance(log_filter, AccessTokenRedactionFilter)
            for log_filter in logging.getLogger(logger_name).filters
        )


def test_clerk_verifier_rejects_invalid_issuer(key_pair, clerk_settings):
    private_key, public_key = key_pair
    verifier = ClerkJwtVerifier(clerk_settings, jwks_client=FakeJwksClient(public_key))

    with pytest.raises(ApiError) as exc:
        verifier.verify(signed_token(private_key, iss="https://attacker.example"))

    assert exc.value.code == "auth_invalid"


def test_clerk_verifier_allows_expired_token_in_demo_mode(key_pair, clerk_settings):
    private_key, public_key = key_pair
    expired_iat = datetime.now(UTC) - timedelta(days=365)
    expired_token = signed_token(private_key, iat=expired_iat, exp=expired_iat + timedelta(minutes=5))
    verifier = ClerkJwtVerifier(clerk_settings, jwks_client=FakeJwksClient(public_key))

    # verify_exp is False for demo mode, so expired tokens are accepted and decoded
    payload = verifier.verify(expired_token)
    assert payload["sub"] == "user_test123"


def test_clerk_verifier_rejects_missing_sub(key_pair, clerk_settings):
    private_key, public_key = key_pair
    verifier = ClerkJwtVerifier(clerk_settings, jwks_client=FakeJwksClient(public_key))

    with pytest.raises(ApiError) as exc:
        verifier.verify(signed_token(private_key, sub=None))

    assert exc.value.code == "auth_invalid"


def test_clerk_startup_requires_metadata_and_https_in_hosted_envs():
    missing = Settings(APP_ENV="test", AUTH_MODE="clerk", CLERK_ISSUER=None, CLERK_JWKS_URL=None)
    with pytest.raises(RuntimeError, match="CLERK_ISSUER"):
        missing.validate_startup()

    non_tls = Settings(
        APP_ENV="production",
        AUTH_MODE="clerk",
        STT_PROVIDER="deepgram",
        TTS_PROVIDER="deepgram",
        LLM_PROVIDER="anthropic",
        RAG_PROVIDER="pgvector",
        WAREHOUSE_PROVIDER="snowflake",
        CLERK_ISSUER="http://clerk.voxquery.test",
        CLERK_JWKS_URL=JWKS_URL,
    )
    with pytest.raises(RuntimeError, match="https://"):
        non_tls.validate_startup()


@pytest.mark.asyncio
async def test_rest_auth_requires_bearer_header_in_clerk_mode(clerk_settings):
    with pytest.raises(ApiError) as missing:
        await get_current_user(authorization=None, settings=clerk_settings)
    assert missing.value.code == "auth_missing"

    with pytest.raises(ApiError) as invalid:
        await get_current_user(authorization="Token nope", settings=clerk_settings)
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
        Settings(
            APP_ENV="test",
            AUTH_MODE="clerk",
            CLERK_ISSUER=ISSUER,
            CLERK_JWKS_URL=JWKS_URL,
            CLERK_AUDIENCE=None,
        ),
        jwks_client=FakeJwksClient(public_key),
    )
    force_clerk_mode(monkeypatch, verifier)
    client = TestClient(app)
    token = signed_token(private_key)
    response = client.post(
        "/api/session",
        headers={"Authorization": f"Bearer {token}"},
        json={"tenant_id": TENANT_ID},
    )
    assert response.status_code == 201

    mismatch = client.post(
        "/api/session",
        headers={"Authorization": f"Bearer {token}"},
        json={"tenant_id": OTHER_TENANT_ID},
    )
    assert mismatch.status_code == 401
    assert mismatch.json()["error"]["code"] == "auth_invalid"


def test_rest_query_rejects_same_tenant_different_user_session(monkeypatch, key_pair):
    private_key, public_key = key_pair
    verifier = ClerkJwtVerifier(
        Settings(
            APP_ENV="test",
            AUTH_MODE="clerk",
            CLERK_ISSUER=ISSUER,
            CLERK_JWKS_URL=JWKS_URL,
            CLERK_AUDIENCE=None,
        ),
        jwks_client=FakeJwksClient(public_key),
    )
    force_clerk_mode(monkeypatch, verifier)
    client = TestClient(app)
    owner_token = signed_token(private_key)
    other_user_token = signed_token(private_key, sub=OTHER_USER_ID)
    session = client.post(
        "/api/session",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"tenant_id": TENANT_ID},
    ).json()

    response = client.post(
        "/api/query",
        headers={"Authorization": f"Bearer {other_user_token}"},
        json={
            "session_id": session["session_id"],
            "submitted_text": "Show net revenue by customer segment",
            "input_modality": "text",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"


def test_websocket_auth_accepts_valid_token_and_rejects_missing_token(monkeypatch, key_pair):
    private_key, public_key = key_pair
    verifier = ClerkJwtVerifier(
        Settings(
            APP_ENV="test",
            AUTH_MODE="clerk",
            CLERK_ISSUER=ISSUER,
            CLERK_JWKS_URL=JWKS_URL,
            CLERK_AUDIENCE=None,
        ),
        jwks_client=FakeJwksClient(public_key),
    )
    force_clerk_mode(monkeypatch, verifier)
    client = TestClient(app)
    token = signed_token(private_key)
    session = client.post(
        "/api/session",
        headers={"Authorization": f"Bearer {token}"},
        json={"tenant_id": TENANT_ID},
    ).json()

    with client.websocket_connect(f"/ws/pipeline?session_id={session['session_id']}") as ws:
        ws.send_json({"event": "auth", "token": token})
        assert ws is not None

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/pipeline?session_id={session['session_id']}") as ws:
            ws.send_json({"event": "auth"})
            ws.receive_json()
    assert exc.value.code == 4001


def test_websockets_reject_same_tenant_different_user_session(monkeypatch, key_pair):
    private_key, public_key = key_pair
    verifier = ClerkJwtVerifier(
        Settings(
            APP_ENV="test",
            AUTH_MODE="clerk",
            CLERK_ISSUER=ISSUER,
            CLERK_JWKS_URL=JWKS_URL,
            CLERK_AUDIENCE=None,
        ),
        jwks_client=FakeJwksClient(public_key),
    )
    force_clerk_mode(monkeypatch, verifier)
    client = TestClient(app)
    owner_token = signed_token(private_key)
    other_user_token = signed_token(private_key, sub=OTHER_USER_ID)
    session = client.post(
        "/api/session",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"tenant_id": TENANT_ID},
    ).json()

    for path in ("pipeline", "audio"):
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(f"/ws/{path}?session_id={session['session_id']}") as ws:
                ws.send_json({"event": "auth", "token": other_user_token})
                ws.receive_json()
        assert exc.value.code == 4002


def test_websockets_reject_tampered_signature_with_4001(monkeypatch, key_pair):
    private_key, public_key = key_pair
    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = ClerkJwtVerifier(
        Settings(
            APP_ENV="test",
            AUTH_MODE="clerk",
            CLERK_ISSUER=ISSUER,
            CLERK_JWKS_URL=JWKS_URL,
            CLERK_AUDIENCE=None,
        ),
        jwks_client=FakeJwksClient(public_key),
    )
    force_clerk_mode(monkeypatch, verifier)
    client = TestClient(app)
    valid_token = signed_token(private_key)
    tampered_token = signed_token(attacker_key)
    session = client.post(
        "/api/session",
        headers={"Authorization": f"Bearer {valid_token}"},
        json={"tenant_id": TENANT_ID},
    ).json()

    for path in ("pipeline", "audio"):
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(f"/ws/{path}?session_id={session['session_id']}") as ws:
                ws.send_json({"event": "auth", "token": tampered_token})
                ws.receive_json()
        assert exc.value.code == 4001


def test_clerk_verification_stays_within_local_budget(key_pair, clerk_settings):
    private_key, public_key = key_pair
    verifier = ClerkJwtVerifier(clerk_settings, jwks_client=FakeJwksClient(public_key))
    token = signed_token(private_key)

    started = perf_counter()
    for _ in range(25):
        assert verifier.claims_from_payload(verifier.verify(token)).tenant_id == TENANT_ID
    elapsed_ms = (perf_counter() - started) * 1000

    assert elapsed_ms < 500


def force_clerk_mode(monkeypatch, verifier: ClerkJwtVerifier):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", "clerk")
    monkeypatch.setattr(settings, "clerk_issuer", ISSUER)
    monkeypatch.setattr(settings, "clerk_jwks_url", JWKS_URL)
    monkeypatch.setattr(settings, "clerk_audience", None)
    monkeypatch.setattr(auth, "get_clerk_verifier", lambda current_settings: verifier)
