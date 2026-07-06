import os

os.environ["APP_ENV"] = "test"
os.environ["AUTH_MODE"] = "fake"
os.environ["SESSION_STORE"] = "memory"
os.environ["STT_PROVIDER"] = "fake"
os.environ["LLM_PROVIDER"] = "fake"
os.environ["RAG_PROVIDER"] = "fake"
os.environ["WAREHOUSE_PROVIDER"] = "fake"
os.environ["SUPABASE_DATABASE_URL"] = ""
os.environ["LANGFUSE_PUBLIC_KEY"] = "fake"
os.environ["LANGFUSE_SECRET_KEY"] = "fake"
os.environ["LANGFUSE_HOST"] = "http://localhost:1111"

import pytest

@pytest.fixture(autouse=True)
def manage_global_test_clients(request):
    module = request.node.module
    if hasattr(module, 'client'):
        with module.client:
            yield
    else:
        yield
