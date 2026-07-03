import logging
import re

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.rest import router as rest_router
from app.api.ws_audio import router as ws_audio_router
from app.api.ws_pipeline import router as ws_pipeline_router
from app.config import get_settings
from app.core.session import build_session_store
from app.models.contracts import ApiError, ErrorCode, ErrorEnvelope, ERROR_MESSAGES
from app.services.events import PipelineEventBus
from app.services.pipeline import PipelineOrchestrator

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

app = FastAPI(title="VoxQuery Voice Subsystem", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.sessions = build_session_store(settings=settings)
app.state.events = PipelineEventBus()
app.state.pipeline = PipelineOrchestrator(
    sessions=app.state.sessions,
    events=app.state.events,
    settings=settings,
)


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
    return {
        "status": "ok",
        "redis": app.state.sessions.health_status(),
        "postgres": "not_configured",
        "version": "local-dev",
    }


app.include_router(rest_router)
app.include_router(ws_pipeline_router)
app.include_router(ws_audio_router)
