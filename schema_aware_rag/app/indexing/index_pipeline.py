"""
index_pipeline.py — Updated to support both DuckDB and Snowflake
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Optional
import yaml

from app.config import settings
from app.warehouse.warehouse_factory import WarehouseFactory
from app.warehouse.base import BaseWarehouseConnector
from app.indexing.embedder import BaseEmbedder, create_embedder
from app.indexing.keyword_index import BM25Index
from app.indexing.vector_store import FAISSVectorStore
from app.metadata.chunker import MetadataChunker
from app.metadata.metric_registry import MetricRegistry
from app.metadata.models import (
    BusinessRule, ColumnMetadata, RagChunk, SampleQuery, TableMetadata,
)

logger = logging.getLogger(__name__)


@dataclass
class IndexingResult:
    success: bool = False
    error: Optional[str] = None
    warehouse_type: str = "unknown"
    tables_extracted: int = 0
    columns_extracted: int = 0
    metrics_loaded: int = 0
    sample_queries_loaded: int = 0
    business_rules_loaded: int = 0
    total_chunks: int = 0
    table_chunks: int = 0
    metric_chunks: int = 0
    example_chunks: int = 0
    rule_chunks: int = 0
    vectors_indexed: int = 0
    bm25_indexed: int = 0
    extraction_time_s: float = 0.0
    embedding_time_s: float = 0.0
    indexing_time_s: float = 0.0
    total_time_s: float = 0.0

    def log_summary(self) -> None:
        logger.info("=" * 60)
        logger.info("INDEXING COMPLETE [%s]", self.warehouse_type.upper())
        logger.info("Status: %s", "✅ SUCCESS" if self.success else "❌ FAILED")
        if self.error:
            logger.error("Error: %s", self.error)
        logger.info("Tables:        %d", self.tables_extracted)
        logger.info("Columns:       %d", self.columns_extracted)
        logger.info("Metrics:       %d", self.metrics_loaded)
        logger.info("Sample Queries:%d", self.sample_queries_loaded)
        logger.info("Total Chunks:  %d", self.total_chunks)
        logger.info("Total Time:    %.2fs", self.total_time_s)
        logger.info("=" * 60)


class IndexPipeline:
    """
    Unified indexing pipeline supporting DuckDB and Snowflake.

    Usage:
        # DuckDB (default)
        pipeline = IndexPipeline()
        result = pipeline.run()

        # Snowflake (auto-detect from config)
        pipeline = IndexPipeline(warehouse_type="snowflake")
        result = pipeline.run()

        # Snowflake with schema setup
        pipeline = IndexPipeline(warehouse_type="snowflake")
        result = pipeline.run()
    """

    def __init__(
        self,
        warehouse_type: Optional[str] = None,
        metrics_path: Optional[str] = None,
        sample_queries_path: Optional[str] = None,
        embedder: Optional[BaseEmbedder] = None,
        # DuckDB-specific
        db_path: Optional[str] = None,
        setup_schema: bool = False,
        schema_sql_path: str = "data/schema_setup.sql",
    ):
        self.warehouse_type = warehouse_type or settings.active_warehouse
        self.metrics_path = metrics_path or settings.metrics_path
        self.sample_queries_path = (
            sample_queries_path or settings.sample_queries_path
        )
        self.embedder = embedder
        self.db_path = db_path
        self.setup_schema = setup_schema
        self.schema_sql_path = schema_sql_path

        self._connector: Optional[BaseWarehouseConnector] = None
        self._embedder: Optional[BaseEmbedder] = None

    def _get_connector(self) -> BaseWarehouseConnector:
        """Get or create warehouse connector."""
        if self._connector is None:
            self._connector = WarehouseFactory.create(self.warehouse_type)
        return self._connector

    def _get_embedder(self) -> BaseEmbedder:
        """Get or create embedder."""
        if self._embedder is None:
            self._embedder = self.embedder or create_embedder(use_cache=True)
        return self._embedder

    # ── Stage 0: DuckDB Schema Setup (optional) ───────────────────

    def _setup_duckdb_schema(self) -> None:
        """Run schema_setup.sql for DuckDB (dev only)."""
        from pathlib import Path
        sql_path = Path(self.schema_sql_path)
        if not sql_path.exists():
            logger.warning("Schema SQL not found at %s", sql_path)
            return

        logger.info("Setting up DuckDB schema...")
        from app.duckdb_connector.connection import DuckDBConnectionManager
        mgr = DuckDBConnectionManager(
            db_path=self.db_path or settings.duckdb_path)
        sql_content = sql_path.read_text()
        statements = [s.strip() for s in sql_content.split(";") if s.strip()]
        with mgr.get_connection() as conn:
            for stmt in statements:
                try:
                    conn.execute(stmt)
                except Exception as e:
                    logger.warning("Schema statement warning: %s", e)

    # ── Stage 1: Extract ──────────────────────────────────────────

    def _extract_tables(self, result: IndexingResult) -> list[TableMetadata]:
        """Extract schema from configured warehouse."""
        logger.info(
            "Stage 1: Extracting schema from %s...",
            self.warehouse_type.upper()
        )
        t0 = time.time()

        connector = self._get_connector()
        tables: list[TableMetadata] = []

        if self.warehouse_type == "snowflake":
            tables = self._extract_from_snowflake(connector)
        else:
            tables = self._extract_from_duckdb(connector)

        result.tables_extracted = len(tables)
        result.columns_extracted = sum(len(t.columns) for t in tables)
        result.extraction_time_s = time.time() - t0

        logger.info(
            "Extracted %d tables, %d columns from %s in %.2fs",
            result.tables_extracted,
            result.columns_extracted,
            self.warehouse_type,
            result.extraction_time_s,
        )
        return tables

    def _extract_from_snowflake(
        self,
        connector: BaseWarehouseConnector,
    ) -> list[TableMetadata]:
        """Use SnowflakeSchemaExtractor for enriched extraction."""
        from app.warehouse.snowflake_connector import SnowflakeConnector
        from app.warehouse.snowflake_extractor import SnowflakeSchemaExtractor

        if not isinstance(connector, SnowflakeConnector):
            raise TypeError("Expected SnowflakeConnector")

        extractor = SnowflakeSchemaExtractor(
            connector=connector,
            include_views=connector.config.include_views,
            sample_rows=connector.config.sample_row_limit,
        )
        return extractor.extract_all_enriched(
            excluded_schemas=connector.config.excluded_schemas
        )

    def _extract_from_duckdb(
        self,
        connector: BaseWarehouseConnector,
    ) -> list[TableMetadata]:
        """Use existing DuckDB extraction pipeline."""
        from app.duckdb_connector.connection import DuckDBConnectionManager
        from app.duckdb_connector.schema_extractor import DuckDBSchemaExtractor
        from app.duckdb_connector.sampler import DuckDBSampler

        mgr = DuckDBConnectionManager(
            db_path=self.db_path or settings.duckdb_path
        )
        extractor = DuckDBSchemaExtractor(mgr, sample_row_limit=5)
        sampler = DuckDBSampler(mgr, sample_size=5)

        raw_tables = extractor.extract_all_tables()
        tables = []

        for raw in raw_tables:
            try:
                profile = sampler.profile_table(
                    raw.schema_name, raw.table_name)
            except Exception:
                profile = None

            columns = []
            for col in raw.columns:
                cm = ColumnMetadata(
                    name=col.column_name,
                    data_type=col.data_type,
                    nullable=col.is_nullable,
                    ordinal_position=col.ordinal_position,
                )
                if profile:
                    prof_col = next(
                        (c for c in profile.column_samples
                         if c.column_name == col.column_name), None
                    )
                    if prof_col:
                        cm.is_likely_metric = prof_col.is_likely_metric
                        cm.is_likely_date = prof_col.is_likely_date
                        cm.approx_distinct = prof_col.approx_distinct
                columns.append(cm)

            desc, synonyms = self._get_duckdb_enrichment(raw.table_name)
            domain = self._infer_duckdb_domain(raw.table_name)

            tables.append(TableMetadata(
                schema_name=raw.schema_name,
                table_name=raw.table_name,
                description=desc,
                domain=domain,
                synonyms=synonyms,
                row_count=raw.row_count,
                columns=columns,
                sample_rows=raw.sample_rows[:3],
            ))

        return tables

    def _infer_duckdb_domain(self, table_name: str) -> str:
        domain_map = {
            "orders": "sales", "order_items": "sales",
            "order_payments": "payments", "order_reviews": "reviews",
            "customers": "customers", "products": "products",
            "sellers": "sellers", "geolocation": "geography",
        }
        return domain_map.get(table_name.lower(), "general")

    def _get_duckdb_enrichment(self, table_name: str) -> tuple[str, list[str]]:
        enrichment = {
            "ORDERS": ("Order-level fact table.", ["orders", "transactions"]),
            "ORDER_ITEMS": ("Line-item detail per order.", ["items", "line items"]),
            "ORDER_PAYMENTS": ("Payment method data.", ["payments"]),
            "ORDER_REVIEWS": ("Customer satisfaction scores.", ["reviews"]),
            "CUSTOMERS": ("Customer master data.", ["customers", "buyers"]),
            "PRODUCTS": ("Product catalog.", ["products", "catalog"]),
            "SELLERS": ("Seller directory.", ["sellers", "vendors"]),
            "GEOLOCATION": ("ZIP code mapping.", ["locations", "regions"]),
        }
        return enrichment.get(table_name.upper(), ("", []))

    # ── Stage 2: Load YAML ────────────────────────────────────────

    def _load_metrics(self, result: IndexingResult) -> MetricRegistry:
        logger.info("Stage 2a: Loading metrics from '%s'...",
                    self.metrics_path)
        registry = MetricRegistry(self.metrics_path)
        result.metrics_loaded = registry.count
        logger.info("Loaded %d metrics", registry.count)
        return registry

    def _load_sample_queries(self, result: IndexingResult) -> list[SampleQuery]:
        logger.info("Stage 2b: Loading sample queries...")
        from pathlib import Path
        path = Path(self.sample_queries_path)
        if not path.exists():
            return []
        with open(path) as f:
            raw = yaml.safe_load(f)
        queries = [SampleQuery(**q) for q in raw.get("sample_queries", [])]
        result.sample_queries_loaded = len(queries)

        # Snowflake: also mine from query history
        if self.warehouse_type == "snowflake":
            mined = self._mine_snowflake_queries()
            queries.extend(mined)
            logger.info("Mined %d queries from Snowflake history", len(mined))
        return queries

    def _mine_snowflake_queries(self) -> list[SampleQuery]:
        """Mine top queries from Snowflake QUERY_HISTORY."""
        try:
            from app.warehouse.snowflake_connector import SnowflakeConnector
            connector = self._get_connector()
            if not isinstance(connector, SnowflakeConnector):
                return []
            history = connector.get_query_history(
                days=connector.config.query_history_days,
                min_executions=connector.config.query_history_min_executions,
                limit=connector.config.query_history_limit,
            )
            queries = []
            for entry in history:
                if len(entry["query_text"]) < 50:
                    continue
                queries.append(SampleQuery(
                    natural_language=f"Query from Snowflake history (exec={entry['execution_count']}x)",
                    paraphrases=[],
                    sql=entry["query_text"],
                    tables_used=[],
                    metrics_used=[],
                    domain=entry.get("schema_name", ""),
                    source="mined",
                    validated=True,
                ))
            return queries
        except Exception as e:
            logger.warning("Query history mining failed: %s", e)
            return []

    def _load_business_rules(self, result: IndexingResult) -> list[BusinessRule]:
        """Load built-in business rules (same for both warehouses)."""
        logger.info("Stage 2c: Loading business rules...")
        rules = [
            BusinessRule(
                name="completed_orders_only",
                description="Revenue needs order_status = 'delivered'",
                rule_text="Always filter ORDERS with WHERE order_status = 'delivered'.",
                sql_pattern="WHERE order_status = 'delivered'",
                applies_to_tables=["ORDERS"],
                applies_to_metrics=["revenue", "order_count"],
                priority=10,
            ),
            BusinessRule(
                name="revenue_net_of_discounts",
                description="Revenue is price * (1 - discount_rate)",
                rule_text="Net revenue: price * (1 - discount_rate). Never use raw price.",
                sql_pattern="price * (1 - discount_rate)",
                applies_to_tables=["ORDER_ITEMS"],
                applies_to_metrics=["revenue"],
                priority=9,
            ),
        ]

        # Add Snowflake-specific rules
        if self.warehouse_type == "snowflake":
            rules.append(BusinessRule(
                name="snowflake_date_syntax",
                description="Use Snowflake date functions",
                rule_text=(
                    "Use Snowflake date syntax: "
                    "DATEADD('day', -30, CURRENT_DATE()), "
                    "DATE_TRUNC('month', col), "
                    "DATEDIFF('day', start, end)"
                ),
                sql_pattern="DATE_TRUNC('month', col)",
                priority=8,
            ))
        else:
            rules.append(BusinessRule(
                name="duckdb_date_syntax",
                description="Use DuckDB date functions",
                rule_text=(
                    "DuckDB: DATE_TRUNC('month', col), "
                    "CURRENT_DATE - INTERVAL '30 days', "
                    "DATEDIFF('day', start, end)"
                ),
                sql_pattern="DATE_TRUNC('month', col)",
                priority=8,
            ))

        result.business_rules_loaded = len(rules)
        return rules

    # ── Stages 3-5: Chunk → Embed → Index ────────────────────────

    def _create_chunks(
        self,
        tables: list[TableMetadata],
        registry: MetricRegistry,
        sample_queries: list[SampleQuery],
        business_rules: list[BusinessRule],
        result: IndexingResult,
    ) -> list[RagChunk]:
        logger.info("Stage 3: Creating chunks...")
        chunker = MetadataChunker()
        chunks = chunker.create_all_chunks(
            tables=tables,
            metrics=registry.list_metrics(),
            sample_queries=sample_queries,
            business_rules=business_rules,
        )
        from app.metadata.models import ChunkType
        result.total_chunks = len(chunks)
        result.table_chunks = sum(
            1 for c in chunks if c.chunk_type == ChunkType.TABLE_CARD)
        result.metric_chunks = sum(
            1 for c in chunks if c.chunk_type == ChunkType.METRIC_CARD)
        result.example_chunks = sum(
            1 for c in chunks if c.chunk_type == ChunkType.QUERY_EXAMPLE)
        result.rule_chunks = sum(
            1 for c in chunks if c.chunk_type == ChunkType.BUSINESS_RULE)
        logger.info("Created %d chunks", result.total_chunks)
        return chunks

    def _embed_chunks(
        self,
        chunks: list[RagChunk],
        result: IndexingResult,
    ) -> list[list[float]]:
        logger.info("Stage 4: Embedding %d chunks...", len(chunks))
        t0 = time.time()
        embedder = self._get_embedder()
        embeddings = embedder.embed_texts([c.text for c in chunks])
        result.embedding_time_s = time.time() - t0
        logger.info("Embedded in %.2fs", result.embedding_time_s)
        return embeddings

    def _build_indexes(
        self,
        chunks: list[RagChunk],
        embeddings: list[list[float]],
        result: IndexingResult,
    ) -> None:
        logger.info("Stage 5: Building indexes...")
        t0 = time.time()
        embedder = self._get_embedder()

        vector_store = FAISSVectorStore(dim=embedder.dimension)
        vector_store.add_chunks(chunks, embeddings)
        vector_store.save()
        result.vectors_indexed = vector_store.num_chunks

        bm25 = BM25Index()
        bm25.build(chunks)
        bm25.save()
        result.bm25_indexed = bm25.num_chunks

        result.indexing_time_s = time.time() - t0
        logger.info(
            "Saved FAISS=%d, BM25=%d in %.2fs",
            result.vectors_indexed,
            result.bm25_indexed,
            result.indexing_time_s,
        )

    # ── Main Entry Point ──────────────────────────────────────────

    def run(self) -> IndexingResult:
        """Execute the full indexing pipeline."""
        result = IndexingResult(warehouse_type=self.warehouse_type)
        t_start = time.time()

        try:
            logger.info("=" * 60)
            logger.info("STARTING INDEXING [%s]", self.warehouse_type.upper())
            logger.info("=" * 60)

            # Stage 0: DuckDB schema setup (optional)
            if self.setup_schema and self.warehouse_type == "duckdb":
                self._setup_duckdb_schema()

            # Stage 1: Extract
            tables = self._extract_tables(result)

            # Stage 2: Load YAML data
            registry = self._load_metrics(result)
            sample_queries = self._load_sample_queries(result)
            business_rules = self._load_business_rules(result)

            # Stage 3: Chunk
            chunks = self._create_chunks(
                tables, registry, sample_queries, business_rules, result
            )
            if not chunks:
                raise ValueError(
                    "No chunks created. Check schema and metrics.yaml.")

            # Stage 4: Embed
            embeddings = self._embed_chunks(chunks, result)

            # Stage 5: Index
            self._build_indexes(chunks, embeddings, result)

            result.success = True

        except Exception as e:
            result.success = False
            result.error = str(e)
            logger.error("Indexing failed: %s", e, exc_info=True)
        finally:
            result.total_time_s = time.time() - t_start
            result.log_summary()

        return result


def run_pipeline(
    warehouse_type: Optional[str] = None,
    setup_schema: bool = False,
    db_path: Optional[str] = None,
) -> IndexingResult:
    """CLI convenience wrapper."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
    )
    pipeline = IndexPipeline(
        warehouse_type=warehouse_type,
        setup_schema=setup_schema,
        db_path=db_path,
    )
    return pipeline.run()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--warehouse", choices=["duckdb", "snowflake"], default=None)
    parser.add_argument("--setup-schema", action="store_true")
    parser.add_argument("--db-path", type=str, default=None)
    args = parser.parse_args()

    result = run_pipeline(
        warehouse_type=args.warehouse,
        setup_schema=args.setup_schema,
        db_path=args.db_path,
    )
    exit(0 if result.success else 1)
