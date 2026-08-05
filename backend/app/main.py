import logging
import re
import warnings

from dotenv import load_dotenv

load_dotenv()

warnings.filterwarnings(
    "ignore", message="Core Pydantic V1 functionality isn't compatible with Python 3.14 or greater."
)

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.briefing import router as briefing_router
from app.api.memory_graph import router as memory_graph_router
from app.api.memory import router as memory_router
from app.api.share import router as share_router
from app.api.workspace import router as workspace_router
from app.api.rest import router as rest_router
from app.api.ws_audio import router as ws_audio_router
from app.api.ws_pipeline import router as ws_pipeline_router
from app.api.ws_tts import router as ws_tts_router
from app.api.telemetry import router as telemetry_router
from app.api.webhooks import router as webhooks_router
from app.audit.store import AuditStore
from app.audit.noop import NoopAuditStore
from app.audit.postgres import PostgresAuditStore
from app.audit.migrations_runner import run_migrations
from app.config import get_settings
from app.core.rate_limit import RateLimiter
from app.core.session import build_session_store
from app.models.contracts import ApiError, ErrorCode, ErrorEnvelope, ERROR_MESSAGES
from app.services.events import PipelineEventBus
from app.services.pipeline import PipelineOrchestrator
from app.services.telemetry import StructuredLogger
from app.llm.claude import ClaudeAdapter, ClaudeStoryteller
from app.rag.pgvector import PgVectorSchemaRetriever
from app.warehouse.routing import TenantRoutingWarehouseConnector
from app.warehouse.snowflake import SnowflakeWarehouseConnector
import asyncpg
from anthropic import AsyncAnthropic
from langfuse.openai import AsyncOpenAI

settings = get_settings()
settings.validate_startup()
logger = logging.getLogger("voxquery.api")
_TOKEN_QUERY_RE = re.compile(r"([?&]token=)[^&\s\"]+")


def redact_token_query_params(value: str) -> str:
    return _TOKEN_QUERY_RE.sub(r"\1<redacted>", value)


class AccessTokenRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_token_query_params(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_token_query_params(arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: redact_token_query_params(value) if isinstance(value, str) else value
                for key, value in record.args.items()
            }
        return True


for logger_name in ("uvicorn.access", "uvicorn.error"):
    logging.getLogger(logger_name).addFilter(AccessTokenRedactionFilter())

audit_store: AuditStore
if settings.supabase_database_url:
    audit_store = PostgresAuditStore(settings.supabase_database_url)
else:
    audit_store = NoopAuditStore()

schema_retriever = None
llm_adapter = None
warehouse_connector = None
storyteller = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_pool = None
    if settings.supabase_database_url:
        await run_migrations(settings.supabase_database_url)

    global schema_retriever, llm_adapter, warehouse_connector, storyteller

    if settings.rag_provider == "pgvector" and settings.supabase_database_url:
        pool = await asyncpg.create_pool(
            settings.supabase_database_url,
            min_size=1,
            max_size=4,
            statement_cache_size=0,
            max_inactive_connection_lifetime=300.0,
            server_settings={
                'tcp_keepalives_idle': '60',
                'tcp_keepalives_interval': '10',
                'tcp_keepalives_count': '5'
            }
        )
        openai_client = AsyncOpenAI(timeout=120.0)
        schema_retriever = PgVectorSchemaRetriever(openai_client=openai_client, db_pool=pool)

    if settings.llm_provider == "claude":
        anthropic_client = (
            AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=120.0)
            if settings.anthropic_api_key
            else AsyncAnthropic(timeout=120.0)
        )
        llm_adapter = ClaudeAdapter(client=anthropic_client)
        storyteller = ClaudeStoryteller(client=anthropic_client)

    if settings.warehouse_provider == "snowflake":
        # Snowflake doesn't need an async initialization pool for this MVP slice
        # The connector will handle it during execute_readonly
        # Use routing connector that supports tenant-specific configurations
        if settings.supabase_database_url:
            if not getattr(schema_retriever, "pool", None):
                # Ensure we have a pool if not created by pgvector
                pool = await asyncpg.create_pool(
                    settings.supabase_database_url,
                    min_size=1,
                    max_size=4,
                    statement_cache_size=0,
                    max_inactive_connection_lifetime=300.0,
                    server_settings={
                        'tcp_keepalives_idle': '60',
                        'tcp_keepalives_interval': '10',
                        'tcp_keepalives_count': '5'
                    }
                )
            else:
                pool = schema_retriever.pool

            # Do not create a global Snowflake pool here. Its credentials would
            # be shared across tenant connectors and could cross tenant data
            # boundaries. TenantRoutingWarehouseConnector resolves each
            # encrypted tenant DSN independently.
            warehouse_connector = TenantRoutingWarehouseConnector(settings=settings, db_pool=pool)
        else:
            dsn = settings.snowflake_dsn or "dummy_dsn"
            warehouse_connector = SnowflakeWarehouseConnector(dsn=dsn)

    app.state.db_pool = (
        getattr(schema_retriever, "pool", None) or db_pool or (pool if "pool" in locals() else None)
    )
    await audit_store.start()
    await app.state.sessions.start()

    # Update pipeline with initialized providers
    app.state.pipeline = PipelineOrchestrator(
        sessions=app.state.sessions,
        events=app.state.events,
        audit=app.state.audit,
        settings=settings,
        schema=schema_retriever,
        llm=llm_adapter,
        warehouse=warehouse_connector,
        story=storyteller,
        db_pool=app.state.db_pool,
    )

    from app.services.briefing_scheduler import start_briefing_scheduler

    if app.state.db_pool and settings.supabase_database_url:
        start_briefing_scheduler(app.state.db_pool, settings, warehouse=warehouse_connector)

    yield
    from app.observability.langfuse import tracer
    if tracer and tracer.langfuse:
        tracer.langfuse.flush()

    await audit_store.stop()
    await app.state.sessions.close()
    await app.state.rate_limiter.close()
    if schema_retriever and getattr(schema_retriever, "pool", None):
        await schema_retriever.pool.close()

    if app.state.db_pool and not getattr(schema_retriever, "pool", None):
        await app.state.db_pool.close()


app = FastAPI(title="VoxQuery Voice Subsystem", version="0.1.0", lifespan=lifespan)
cors_kwargs: dict = {
    "allow_credentials": True,
    "allow_methods": ["*"],
    "allow_headers": ["*"],
}
if "*" in settings.cors_origins:
    cors_kwargs["allow_origins"] = ["*"]
else:
    cors_kwargs["allow_origins"] = settings.cors_origins
    if settings.cors_origin_regex:
        cors_kwargs["allow_origin_regex"] = settings.cors_origin_regex

app.add_middleware(CORSMiddleware, **cors_kwargs)

app.state.audit = audit_store
app.state.sessions = build_session_store(settings=settings)
app.state.rate_limiter = RateLimiter(
    settings=settings,
    client=getattr(app.state.sessions, "client", None),
)
app.state.events = PipelineEventBus()
# The pipeline is fully initialized in the lifespan context now.
app.state.pipeline = PipelineOrchestrator(
    sessions=app.state.sessions,
    events=app.state.events,
    audit=app.state.audit,
    settings=settings,
)
# Root telemetry logger — unbound. Route handlers call .bind(session_id=..., tenant_id=...)
# to create a request-scoped child logger. See services/telemetry.py.
app.state.telemetry = StructuredLogger()


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    # Non-error status codes (e.g. 202 Accepted for polling turn_processing) are expected
    # control flow and should not pollute logs with warning-level 'api_error' entries.
    if exc.status_code < 400:
        logger.debug(
            "turn_processing path=%s code=%s status=%s",
            request.url.path,
            exc.code.value,
            exc.status_code,
        )
    else:
        logger.warning(
            "api_error path=%s code=%s status=%s detail=%s",
            request.url.path,
            exc.code.value,
            exc.status_code,
            exc.detail,
        )
    detail = None if settings.app_env == "production" else exc.detail
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorEnvelope(
            error={
                "code": exc.code.value,
                "message": ERROR_MESSAGES[exc.code],
                "detail": detail,
            }
        ).model_dump(mode="json"),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    message = str(exc)
    code = ErrorCode.query_too_long if "at most 500" in message else ErrorCode.query_empty
    return JSONResponse(
        status_code=400,
        content=ErrorEnvelope(
            error={
                "code": code.value,
                "message": ERROR_MESSAGES[code],
                "detail": None if settings.app_env == "production" else message,
            }
        ).model_dump(mode="json"),
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Log the full traceback for any unhandled exception (500) so we can trace it immediately.
    logger.exception(
        "unhandled_exception path=%s method=%s error=%s", request.url.path, request.method, str(exc)
    )

    code = ErrorCode.internal_error
    return JSONResponse(
        status_code=500,
        content=ErrorEnvelope(
            error={
                "code": code.value,
                "message": ERROR_MESSAGES[code],
                "detail": None if settings.app_env == "production" else str(exc),
            }
        ).model_dump(mode="json"),
    )


@app.get("/health")
async def health() -> dict[str, str]:
    audit_health = await app.state.audit.check_health()
    return {
        "status": "ok",
        "redis": await app.state.sessions.health_status(),
        "postgres": audit_health,
        "version": "local-dev",
    }


@app.get("/api/version")
async def get_version() -> dict[str, str]:
    import os
    import subprocess

    git_sha = os.environ.get("GIT_SHA", "")
    if not git_sha:
        try:
            git_sha = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], text=True
            ).strip()
        except Exception:
            git_sha = "unknown"
    return {
        "git_sha": git_sha,
        "version": "1.0.0",
    }


app.include_router(rest_router)
app.include_router(ws_pipeline_router)
app.include_router(ws_audio_router)
app.include_router(ws_tts_router)
app.include_router(telemetry_router)
app.include_router(webhooks_router)
app.include_router(briefing_router)
app.include_router(memory_graph_router)
app.include_router(memory_router)
app.include_router(share_router)
app.include_router(workspace_router)
