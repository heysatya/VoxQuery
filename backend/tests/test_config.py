import pytest
from app.config import Settings


def test_production_guardrails_reject_fake_providers():
    base_kwargs = {
        "APP_ENV": "production",
        "SESSION_STORE": "redis",
        "UPSTASH_REDIS_URL": "rediss://localhost:6379",
        "SUPABASE_DATABASE_URL": "postgresql://localhost:5432/voxquery",
        "PUBLIC_APP_URL": "https://voxquery.test",
        "CLERK_ISSUER": "https://clerk.voxquery.test",
        "CLERK_JWKS_URL": "https://clerk.voxquery.test/.well-known/jwks.json",
        "DEEPGRAM_API_KEY": "dummy",
        "OPENAI_API_KEY": "dummy",
    }

    # Test AUTH_MODE
    with pytest.raises(RuntimeError, match="AUTH_MODE=fake is only allowed"):
        Settings(**base_kwargs, AUTH_MODE="fake").validate_startup()

    # Base valid config for production
    valid_prod_kwargs = {
        **base_kwargs,
        "AUTH_MODE": "clerk",
        "STT_PROVIDER": "deepgram",
        "TTS_PROVIDER": "deepgram",
        "LLM_PROVIDER": "anthropic",
        "RAG_PROVIDER": "pgvector",
        "WAREHOUSE_PROVIDER": "snowflake",
        "SNOWFLAKE_DSN": "dummy-dsn",
        "FERNET_KEY": "dummy-key",
    }

    # Verify base valid config passes
    Settings(**valid_prod_kwargs).validate_startup()

    # Test STT_PROVIDER
    with pytest.raises(RuntimeError, match="STT_PROVIDER=fake is not allowed"):
        Settings(**{**valid_prod_kwargs, "STT_PROVIDER": "fake"}).validate_startup()

    # Test TTS_PROVIDER
    with pytest.raises(RuntimeError, match="TTS_PROVIDER=fake is not allowed"):
        Settings(**{**valid_prod_kwargs, "TTS_PROVIDER": "fake"}).validate_startup()

    # Test LLM_PROVIDER
    with pytest.raises(RuntimeError, match="LLM_PROVIDER=fake is not allowed"):
        Settings(**{**valid_prod_kwargs, "LLM_PROVIDER": "fake"}).validate_startup()

    # Test RAG_PROVIDER
    with pytest.raises(RuntimeError, match="RAG_PROVIDER=fake is not allowed"):
        Settings(**{**valid_prod_kwargs, "RAG_PROVIDER": "fake"}).validate_startup()

    # Test WAREHOUSE_PROVIDER
    with pytest.raises(RuntimeError, match="WAREHOUSE_PROVIDER=fake is not allowed"):
        Settings(**{**valid_prod_kwargs, "WAREHOUSE_PROVIDER": "fake"}).validate_startup()


def test_development_allows_fake_providers():
    # Should not raise
    Settings(
        APP_ENV="development",
        AUTH_MODE="fake",
        STT_PROVIDER="fake",
        TTS_PROVIDER="fake",
        LLM_PROVIDER="fake",
        RAG_PROVIDER="fake",
        WAREHOUSE_PROVIDER="fake",
    ).validate_startup()


def test_production_guardrails_require_keys():
    """
    BEHAVIOR SPEC:
    Given APP_ENV is set to "staging" or "production",
    when the application configuration is validated on startup,
    then it must raise a RuntimeError if FERNET_KEY or SNOWFLAKE_DSN are missing,
    ensuring that tenant credentials and encryption keys are strictly enforced in live environments.
    """
    base_prod_kwargs = {
        "APP_ENV": "production",
        "AUTH_MODE": "clerk",
        "SESSION_STORE": "redis",
        "UPSTASH_REDIS_URL": "rediss://localhost:6379",
        "SUPABASE_DATABASE_URL": "postgresql://localhost:5432/voxquery",
        "PUBLIC_APP_URL": "https://voxquery.test",
        "CLERK_ISSUER": "https://clerk.voxquery.test",
        "CLERK_JWKS_URL": "https://clerk.voxquery.test/.well-known/jwks.json",
        "STT_PROVIDER": "deepgram",
        "TTS_PROVIDER": "deepgram",
        "DEEPGRAM_API_KEY": "dummy",
        "OPENAI_API_KEY": "dummy",
        "LLM_PROVIDER": "anthropic",
        "RAG_PROVIDER": "pgvector",
        "WAREHOUSE_PROVIDER": "snowflake",
    }

    # Missing FERNET_KEY
    with pytest.raises(RuntimeError, match="FERNET_KEY is required in staging/production"):
        Settings(**{**base_prod_kwargs, "FERNET_KEY": None}).validate_startup()

    # Missing SUPABASE_DATABASE_URL
    with pytest.raises(RuntimeError, match="SUPABASE_DATABASE_URL is required"):
        Settings(**{**base_prod_kwargs, "SUPABASE_DATABASE_URL": None}).validate_startup()

    # Valid config passes
    Settings(**base_prod_kwargs).validate_startup()
