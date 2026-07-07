import logging
import re
import warnings

from dotenv import load_dotenv
load_dotenv()

warnings.filterwarnings(
    "ignore",
    message="Core Pydantic V1 functionality isn't compatible with Python 3.14 or greater."
)

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.rest import router as rest_router
from app.api.ws_audio import router as ws_audio_router
from app.api.ws_pipeline import router as ws_pipeline_router
from app.api.ws_tts import router as ws_tts_router
from app.api.telemetry import router as telemetry_router
from app.audit.store import AuditStore
from app.audit.noop import NoopAuditStore
from app.audit.postgres import PostgresAuditStore
from app.audit.migrations_runner import run_migrations
from app.config import get_settings
from app.core.session import build_session_store
from app.models.contracts import ApiError, ErrorCode, ErrorEnvelope, ERROR_MESSAGES
from app.services.events import PipelineEventBus
from app.services.pipeline import PipelineOrchestrator
from app.services.telemetry import StructuredLogger
from app.llm.claude import ClaudeAdapter, ClaudeStoryteller
from app.rag.pgvector import PgVectorSchemaRetriever
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
    if settings.supabase_database_url:
        await run_migrations(settings.supabase_database_url)
    
    global schema_retriever, llm_adapter, warehouse_connector, storyteller
    
    if settings.rag_provider == "pgvector" and settings.supabase_database_url:
        pool = await asyncpg.create_pool(settings.supabase_database_url, min_size=1, max_size=4, statement_cache_size=0)
        openai_client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else AsyncOpenAI()
        schema_retriever = PgVectorSchemaRetriever(openai_client=openai_client, db_pool=pool)
        
    if settings.llm_provider == "claude":
        anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else AsyncAnthropic()
        llm_adapter = ClaudeAdapter(client=anthropic_client)
        storyteller = ClaudeStoryteller(client=anthropic_client)
        
    if settings.warehouse_provider == "snowflake":
        # Snowflake doesn't need an async initialization pool for this MVP slice
        # The connector will handle it during execute_readonly
        warehouse_connector = SnowflakeWarehouseConnector(dsn="dummy_dsn")
        
    await audit_store.start()
    
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
    )
    
    yield
    await audit_store.stop()
    if schema_retriever and getattr(schema_retriever, "pool", None):
        await schema_retriever.pool.close()

app = FastAPI(title="VoxQuery Voice Subsystem", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.audit = audit_store
app.state.sessions = build_session_store(settings=settings)
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
    detail = None if settings.app_env == "production" else exc.detail
    if settings.app_env != "production":
        logger.warning(
            "api_error path=%s code=%s detail=%s",
            request.url.path,
            exc.code.value,
            detail,
        )
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


@app.get("/health")
async def health() -> dict[str, str]:
    audit_health = await app.state.audit.check_health()
    return {
        "status": "ok",
        "redis": app.state.sessions.health_status(),
        "postgres": audit_health,
        "version": "local-dev",
    }


app.include_router(rest_router)
app.include_router(ws_pipeline_router)
app.include_router(ws_audio_router)
app.include_router(ws_tts_router)
app.include_router(telemetry_router)
