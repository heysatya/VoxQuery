import pytest
from app.config import Settings

def test_production_guardrails_reject_fake_providers():
    base_kwargs = {
        "APP_ENV": "production",
        "SESSION_STORE": "memory",  # to avoid upstash validation for now
        "CLERK_ISSUER": "https://clerk.voxquery.test",
        "CLERK_JWKS_URL": "https://clerk.voxquery.test/.well-known/jwks.json",
        "DEEPGRAM_API_KEY": "dummy",
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
