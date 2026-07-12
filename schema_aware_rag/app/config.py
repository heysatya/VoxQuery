"""
config.py — Updated with Snowflake configuration
"""

from pathlib import Path
from typing import Literal, Optional
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SnowflakeConfig(BaseSettings):
    """
    Snowflake connection configuration.
    Supports both password and key-pair authentication.
    """

    model_config = SettingsConfigDict(
        env_prefix="SNOWFLAKE_",
        extra="ignore",
    )

    # ── Connection ────────────────────────────────────────────────
    account: str = ""                    # e.g. xy12345.us-east-1
    user: str = ""
    password: str = Field(default="", repr=False)

    # Key-pair auth (preferred over password)
    private_key_path: str = ""           # path to .p8 key file
    private_key_passphrase: str = Field(default="", repr=False)

    # ── Warehouse & Database ──────────────────────────────────────
    warehouse: str = ""                  # e.g. ANALYTICS_WH
    database: str = ""                   # e.g. PROD_DB
    schema: str = "PUBLIC"              # default schema
    role: str = ""                       # e.g. ANALYTICS_ROLE

    # ── Connection Behavior ───────────────────────────────────────
    login_timeout: int = 60
    network_timeout: int = 30
    query_timeout: int = 300
    max_connection_pool_size: int = 10

    # ── Extraction Settings ───────────────────────────────────────
    excluded_schemas: list[str] = Field(
        default=[
            "INFORMATION_SCHEMA",
            "SNOWFLAKE",
            "SNOWFLAKE_SAMPLE_DATA",
        ]
    )
    sample_row_limit: int = 5
    max_tables_per_extraction: int = 5000
    include_views: bool = True
    include_external_tables: bool = False

    # ── Query History Mining ──────────────────────────────────────
    query_history_days: int = 90
    query_history_min_executions: int = 3
    query_history_limit: int = 200

    @property
    def has_credentials(self) -> bool:
        """Check if minimum credentials are configured."""
        return bool(self.account and self.user)

    @property
    def uses_key_pair_auth(self) -> bool:
        """True if using key-pair authentication."""
        return bool(self.private_key_path)

    @property
    def connection_string(self) -> str:
        """SQLAlchemy-compatible connection string."""
        return (
            f"snowflake://{self.user}:{self.password}@"
            f"{self.account}/{self.database}/{self.schema}"
            f"?warehouse={self.warehouse}&role={self.role}"
        )


class Settings(BaseSettings):
    """Application settings — now with Snowflake support."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ───────────────────────────────────────────────
    app_name: str = "VDA Schema-Aware RAG"
    app_env: Literal["development", "staging", "production"] = "development"
    debug: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # ── Warehouse Selection ───────────────────────────────────────
    warehouse_type: Literal["duckdb", "snowflake", "auto"] = "duckdb"

    # ── DuckDB ────────────────────────────────────────────────────
    duckdb_path: str = "data/warehouse.duckdb"
    duckdb_read_only: bool = False
    duckdb_max_memory: str = "2GB"
    duckdb_threads: int = 4

    # ── Snowflake (nested config) ─────────────────────────────────
    snowflake: SnowflakeConfig = Field(default_factory=SnowflakeConfig)

    # ── Embeddings ────────────────────────────────────────────────
    embedding_provider: Literal["openai", "local"] = "local"
    openai_api_key: str = Field(default="", repr=False)
    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dimensions: int = 1536
    local_embedding_model: str = "BAAI/bge-small-en-v1.5"

    # ── FAISS ─────────────────────────────────────────────────────
    faiss_index_path: str = "data/indexes/faiss.index"
    faiss_chunks_path: str = "data/indexes/chunks.jsonl"
    faiss_dimension: int = 1536

    # ── BM25 ──────────────────────────────────────────────────────
    bm25_index_path: str = "data/indexes/bm25.pkl"

    # ── Retrieval ─────────────────────────────────────────────────
    default_top_k: int = 10
    default_token_budget: int = 2500
    max_token_budget: int = 3000
    rrf_k: int = 60

    # ── Data Paths ────────────────────────────────────────────────
    metrics_path: str = "data/metrics.yaml"
    sample_queries_path: str = "data/sample_queries.yaml"

    # ── API ───────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # ── Computed Properties ───────────────────────────────────────
    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def active_warehouse(self) -> str:
        """Which warehouse is currently active."""
        if self.warehouse_type == "auto":
            return "snowflake" if self.snowflake.has_credentials else "duckdb"
        return self.warehouse_type

    def ensure_directories(self) -> None:
        for d in ["data", "data/indexes", "logs"]:
            Path(d).mkdir(parents=True, exist_ok=True)


settings = Settings()
