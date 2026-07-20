import os

TEST_ENV = {
    "APP_ENV": "test",
    "AUTH_MODE": "fake",
    "SESSION_STORE": "memory",
    "STT_PROVIDER": "fake",
    "TTS_PROVIDER": "fake",
    "LLM_PROVIDER": "fake",
    "RAG_PROVIDER": "fake",
    "WAREHOUSE_PROVIDER": "fake",
    "SUPABASE_DATABASE_URL": "",
    "SNOWFLAKE_DSN": "",
    "DEEPGRAM_API_KEY": "",
    "ANTHROPIC_API_KEY": "",
    "CLERK_ISSUER": "",
    "CLERK_JWKS_URL": "",
    "CLERK_AUDIENCE": "",
    "LANGFUSE_PUBLIC_KEY": "fake",
    "LANGFUSE_SECRET_KEY": "fake",
    "LANGFUSE_HOST": "http://localhost:1111",
}

os.environ.update(TEST_ENV)

import pytest

@pytest.fixture(autouse=True)
def manage_global_test_clients(request):
    os.environ.update(TEST_ENV)
    from app.config import get_settings

    get_settings.cache_clear()
    module = request.node.module
    if hasattr(module, 'client'):
        with module.client:
            yield
    else:
        yield
    get_settings.cache_clear()

import asyncio

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
