"""
main.py
───────
FastAPI application for the Schema-Aware RAG Layer.

Endpoints:
    POST /retrieve          Main retrieval endpoint
    POST /index             Trigger re-indexing
    GET  /health            Health check
    GET  /stats             Index statistics
    GET  /metrics           List registered metrics

Design decisions:
- Lifespan context manager for startup/shutdown
- Dependency injection for retriever (testable)
- Structured error responses (not raw exceptions)
- Request logging via middleware
- CORS enabled for local development
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.indexing.index_pipeline import IndexPipeline, IndexingResult
from app.metadata.metric_registry import MetricRegistry
from app.metadata.models import ContextBundle
from app.retrieval.context_builder import ContextBuilder
from app.retrieval.hybrid_retriever import HybridRetriever, RetrievalConfig

# ─────────────────────────────────────────────────────────────────────
# Logging Setup
# ─────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Application State
# ─────────────────────────────────────────────────────────────────────


class AppState:
    """Global application state (shared across requests)."""
    retriever: Optional[HybridRetriever] = None
    context_builder: Optional[ContextBuilder] = None
    metric_registry: Optional[MetricRegistry] = None
    is_ready: bool = False
    startup_error: Optional[str] = None


app_state = AppState()


# ─────────────────────────────────────────────────────────────────────
# Lifespan (Startup / Shutdown)
# ─────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Loads indexes at startup so the first request is fast.
    """
    logger.info("=" * 50)
    logger.info("VDA Schema-Aware RAG Layer starting up...")
    logger.info("=" * 50)

    try:
        # Initialize retriever (loads FAISS + BM25 from disk)
        app_state.retriever = HybridRetriever()
        app_state.retriever.load_indexes()

        # Initialize context builder
        app_state.context_builder = ContextBuilder(
            token_budget=settings.default_token_budget,
            max_budget=settings.max_token_budget,
        )

        # Initialize metric registry
        app_state.metric_registry = MetricRegistry(settings.metrics_path)

        app_state.is_ready = True
        logger.info("✅ Application ready")

    except Exception as e:
        app_state.startup_error = str(e)
        logger.error("❌ Startup failed: %s", e)
        logger.warning(
            "Starting in degraded mode. Run the indexing pipeline first:\n"
            "  python -m app.indexing.index_pipeline --setup-schema"
        )

    yield  # Application runs here

    # Shutdown
    logger.info("Application shutting down...")


# ─────────────────────────────────────────────────────────────────────
# FastAPI App
# ─────────────────────────────────────────────────────────────────────


app = FastAPI(
    title="VDA Schema-Aware RAG Layer",
    description=(
        "Schema-aware retrieval API for the Voice-Driven Data Analyst. "
        "Retrieves relevant warehouse context (tables, metrics, examples) "
        "for natural language analytics queries."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS (for local development with Next.js frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────
# Request Logging Middleware
# ─────────────────────────────────────────────────────────────────────


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log request latency and status for every endpoint."""
    t_start = time.time()
    response = await call_next(request)
    latency_ms = (time.time() - t_start) * 1000

    logger.info(
        "%s %s → %d (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        latency_ms,
    )
    return response


# ─────────────────────────────────────────────────────────────────────
# Request / Response Models
# ─────────────────────────────────────────────────────────────────────


class RetrieveRequest(BaseModel):
    """Request body for the /retrieve endpoint."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Natural language analytics question",
        examples=["What was revenue by region last quarter?"],
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=30,
        description="Number of chunks to retrieve",
    )
    token_budget: int = Field(
        default=2500,
        ge=500,
        le=3000,
        description="Maximum tokens in the context bundle",
    )

    # Optional filters
    domain_filter: Optional[str] = Field(
        default=None,
        description="Filter to specific domain (sales, customers, products)",
    )
    certified_only: bool = Field(
        default=False,
        description="Only return certified metrics",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "query": "What was revenue by region last quarter?",
                "top_k": 10,
                "token_budget": 2500,
            }
        }


class RetrieveResponse(BaseModel):
    """Response body from the /retrieve endpoint."""

    query: str
    rewritten_query: str

    context: dict = Field(
        description="Structured context bundle with tables, metrics, examples, rules"
    )
    total_tokens: int
    chunks_used: list[dict]

    # Diagnostic metadata
    retrieval_metadata: dict = Field(
        description="Retrieval diagnostics (latency, candidate counts, etc.)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "query": "What was revenue by region last quarter?",
                "rewritten_query": "What was revenue by region last quarter? sales net sales topline",
                "context": {
                    "tables": ["Table: main.ORDERS\n..."],
                    "metrics": ["⭐ Metric: Revenue [CERTIFIED]\n..."],
                    "examples": ["Q: Revenue by region\nSQL: SELECT region, SUM(...)"],
                    "business_rules": ["Always filter WHERE order_status = 'delivered'"],
                },
                "total_tokens": 1850,
                "chunks_used": [
                    {"id": "...", "type": "metric_card", "score": 0.95}
                ],
                "retrieval_metadata": {
                    "latency_ms": 145.3,
                    "vector_candidates": 30,
                    "bm25_candidates": 30,
                    "returned_chunks": 8,
                },
            }
        }


class IndexRequest(BaseModel):
    """Request body for the /index endpoint."""
    setup_schema: bool = Field(
        default=False,
        description="Run schema_setup.sql before indexing",
    )
    db_path: Optional[str] = Field(
        default=None,
        description="Override database path",
    )


class IndexResponse(BaseModel):
    """Response body from the /index endpoint."""
    success: bool
    message: str
    stats: Optional[dict] = None


class ErrorResponse(BaseModel):
    """Structured error response."""
    error: str
    detail: Optional[str] = None
    suggestion: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────
# Dependency Injection
# ─────────────────────────────────────────────────────────────────────


def get_retriever() -> HybridRetriever:
    """Dependency: get the initialized retriever."""
    if not app_state.is_ready or app_state.retriever is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "RAG service not ready. "
                "Run indexing pipeline first: "
                "POST /index with {'setup_schema': true}"
            ),
        )
    return app_state.retriever


def get_context_builder() -> ContextBuilder:
    """Dependency: get the context builder."""
    if app_state.context_builder is None:
        return ContextBuilder()
    return app_state.context_builder


def get_metric_registry() -> Optional[MetricRegistry]:
    """Dependency: get the metric registry (may be None)."""
    return app_state.metric_registry


# ─────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────


@app.post(
    "/retrieve",
    response_model=RetrieveResponse,
    summary="Retrieve schema context for a natural language query",
    tags=["retrieval"],
)
async def retrieve(
    request: RetrieveRequest,
    retriever: HybridRetriever = Depends(get_retriever),
    builder: ContextBuilder = Depends(get_context_builder),
) -> RetrieveResponse:
    """
    Main retrieval endpoint.

    Given a natural language analytics question, returns a structured
    context bundle containing relevant tables, metrics, sample queries,
    and business rules for the SQL generation layer.

    Example questions:
    - "What was revenue by region last quarter?"
    - "Show me the top 5 products by sales"
    - "How many active customers do we have?"
    """
    try:
        # Build retrieval config
        config = RetrievalConfig(
            top_k=request.top_k,
            domain_filter=request.domain_filter,
            certified_only=request.certified_only,
        )

        # Retrieve chunks
        retrieval_result = retriever.retrieve(
            query=request.query,
            config=config,
        )

        # Build context bundle
        bundle = builder.build(
            retrieval_result=retrieval_result,
            extra_token_budget=request.token_budget,
        )

        # Build diagnostic metadata
        metadata = {
            "latency_ms": round(retrieval_result.latency_ms, 2),
            "vector_latency_ms": round(retrieval_result.vector_latency_ms, 2),
            "bm25_latency_ms": round(retrieval_result.bm25_latency_ms, 2),
            "vector_candidates": retrieval_result.vector_candidates,
            "bm25_candidates": retrieval_result.bm25_candidates,
            "fused_candidates": retrieval_result.fused_candidates,
            "returned_chunks": retrieval_result.returned_chunks,
            "degraded_mode": retrieval_result.degraded_mode,
            "detected_metrics": retrieval_result.rewritten_query.detected_metrics,
            "detected_tables": retrieval_result.rewritten_query.detected_tables,
            "detected_domain": retrieval_result.rewritten_query.detected_domain,
        }

        return RetrieveResponse(
            query=request.query,
            rewritten_query=retrieval_result.rewritten_query.get_retrieval_query(),
            context=bundle.context.model_dump(),
            total_tokens=bundle.total_tokens,
            chunks_used=bundle.chunks_used,
            retrieval_metadata=metadata,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Retrieval error: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Retrieval failed: {str(e)}",
        )


@app.post(
    "/index",
    response_model=IndexResponse,
    summary="Trigger schema re-indexing",
    tags=["admin"],
)
async def trigger_indexing(
    request: IndexRequest,
    background_tasks: BackgroundTasks,
) -> IndexResponse:
    """
    Trigger a full schema re-indexing in the background.

    This runs the complete pipeline:
    1. Extract schema from DuckDB
    2. Load metrics and sample queries from YAML
    3. Create chunks
    4. Embed with configured model
    5. Save FAISS + BM25 indexes

    After indexing completes, call GET /health to verify readiness.
    """

    def run_indexing(setup_schema: bool, db_path: Optional[str]):
        """Background task for indexing."""
        pipeline = IndexPipeline(
            db_path=db_path,
            setup_schema=setup_schema,
        )
        result = pipeline.run()

        if result.success:
            # Reload indexes into running application
            try:
                new_retriever = HybridRetriever()
                new_retriever.load_indexes()
                app_state.retriever = new_retriever
                app_state.is_ready = True
                app_state.startup_error = None
                logger.info("✅ Indexes reloaded successfully")
            except Exception as e:
                logger.error("Failed to reload indexes: %s", e)
        else:
            logger.error("Indexing failed: %s", result.error)

    background_tasks.add_task(
        run_indexing,
        setup_schema=request.setup_schema,
        db_path=request.db_path,
    )

    return IndexResponse(
        success=True,
        message=(
            "Indexing started in background. "
            "This may take 30-120 seconds depending on database size. "
            "Check GET /health for readiness."
        ),
    )


@app.get(
    "/health",
    summary="Health check",
    tags=["system"],
)
async def health_check() -> dict:
    """
    Check if the service is healthy and ready to serve requests.
    """
    if not app_state.is_ready:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "error": app_state.startup_error,
                "action": "POST /index with {'setup_schema': true}",
            },
        )

    retriever = app_state.retriever
    vector_ok = (
        retriever._vector_store is not None
        and not retriever._vector_store.is_empty
    )
    bm25_ok = (
        retriever._bm25_index is not None
        and not retriever._bm25_index.is_empty
    )

    return {
        "status": "healthy" if (vector_ok or bm25_ok) else "degraded",
        "indexes": {
            "vector_store": "ok" if vector_ok else "unavailable",
            "bm25_index": "ok" if bm25_ok else "unavailable",
        },
        "chunks": {
            "vector": retriever._vector_store.num_chunks if vector_ok else 0,
            "bm25": retriever._bm25_index.num_chunks if bm25_ok else 0,
        },
        "embedding_provider": (
            retriever._embedder.provider_name
            if retriever._embedder else "not_loaded"
        ),
    }


@app.get(
    "/stats",
    summary="Index statistics",
    tags=["system"],
)
async def get_stats(
    retriever: HybridRetriever = Depends(get_retriever),
) -> dict:
    """Return detailed index statistics."""
    return retriever.get_stats()


@app.get(
    "/metrics",
    summary="List registered business metrics",
    tags=["metadata"],
)
async def list_metrics(
    registry: Optional[MetricRegistry] = Depends(get_metric_registry),
    certified_only: bool = False,
) -> dict:
    """
    List all registered business metrics.

    Args:
        certified_only: If true, return only certified metrics
    """
    if registry is None:
        raise HTTPException(
            status_code=503,
            detail="Metric registry not loaded",
        )

    metrics = (
        registry.list_certified()
        if certified_only
        else registry.list_metrics()
    )

    return {
        "total": len(metrics),
        "certified_count": len(registry.list_certified()),
        "metrics": [
            {
                "name": m.name,
                "display_name": m.display_name,
                "description": m.description,
                "certified": m.certified,
                "synonyms": m.synonyms,
                "source_table": m.source_table,
            }
            for m in metrics
        ],
    }


@app.get(
    "/",
    summary="Root",
    include_in_schema=False,
)
async def root() -> dict:
    """Root endpoint — returns API info."""
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "retrieve": "POST /retrieve",
    }


# ─────────────────────────────────────────────────────────────────────
# Error Handlers
# ─────────────────────────────────────────────────────────────────────


@app.exception_handler(404)
async def not_found_handler(request: Request, exc) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": "endpoint_not_found", "path": str(request.url.path)},
    )


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc) -> JSONResponse:
    logger.error("Unhandled error: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "detail": str(exc),
        },
    )
