from __future__ import annotations

from uuid import UUID

from app.models.contracts import ChartType, ResultPayload, ResultShape, SchemaChunk
from app.rag.retriever import SchemaRetriever
from app.llm.adapter import LlmAdapter, SqlGenerationResult
from app.warehouse.connector import WarehouseConnector


class FakeSchemaRetriever(SchemaRetriever):
    async def retrieve(self, submitted_text: str, tenant_id: UUID) -> tuple[list[SchemaChunk], float]:
        return [
            SchemaChunk(
                source_ref="order_items.price",
                table="order_items",
                column="price",
                content="Order item sale price. Used with discount_rate and freight_value for revenue metrics.",
                similarity=0.91,
            ),
            SchemaChunk(
                source_ref="order_items.discount_rate",
                table="order_items",
                column="discount_rate",
                content="Discount rate applied to order item price. Net revenue subtracts this discount.",
                similarity=0.90,
            ),
            SchemaChunk(
                source_ref="order_items.freight_value",
                table="order_items",
                column="freight_value",
                content="Shipping or freight value. Gross revenue can include freight_value.",
                similarity=0.88,
            ),
            SchemaChunk(
                source_ref="orders.order_purchase_timestamp",
                table="orders",
                column="order_purchase_timestamp",
                content="Date the customer order was placed.",
                similarity=0.79,
            ),
            SchemaChunk(
                source_ref="orders.order_delivered_customer_date",
                table="orders",
                column="order_delivered_customer_date",
                content="Date the order was delivered to the customer. Used for delivery performance.",
                similarity=0.77,
            ),
            SchemaChunk(
                source_ref="customers.customer_segment",
                table="customers",
                column="customer_segment",
                content="Executive-facing customer segment dimension. join_path: customers.customer_id -> orders.customer_id -> order_items.order_id",
                similarity=0.72,
            ),
            SchemaChunk(
                source_ref="geolocation.geolocation_state",
                table="geolocation",
                column="geolocation_state",
                content="Customer geography state dimension. join_path: geolocation.zip_code_prefix -> customers.customer_zip_code_prefix",
                similarity=0.70,
            ),
            SchemaChunk(
                source_ref="products.product_category_name",
                table="products",
                column="product_category_name",
                content="Product category dimension. join_path: products.product_id -> order_items.product_id",
                similarity=0.68,
            ),
        ], 0.86


class FakeSqlGenerator(LlmAdapter):
    async def generate_sql(
        self,
        submitted_text: str,
        *,
        resolved_metric: str | None = None,
        feedback: str | None = None,
    ) -> SqlGenerationResult:
        metric = _metric_column(resolved_metric or submitted_text)
        dimension = _dimension_column(submitted_text)
        confidence = 0.87 if resolved_metric or "revenue" not in submitted_text.lower() else 0.58
        return SqlGenerationResult(
            sql=_revenue_sql(metric, dimension),
            llm_self_confidence=confidence,
            validation_passed=True,
        )

    async def generate_clarification(self, dominant_signal: str) -> tuple[str, list[str]]:
        return clarification_options_for_signal()


class FakeWarehouseConnector(WarehouseConnector):
    async def execute_readonly(self, sql: str, *, snowflake_role: str) -> tuple[ResultPayload, ResultShape]:
        if "customer_segment" in sql:
            columns = ["customer_segment", "total_net_revenue"]
            rows = [["Enterprise", 1240000], ["Consumer", 830000], ["Small Business", 410000]]
            summary = "Enterprise leads net revenue in the stubbed e-commerce result set."
        elif "geolocation_state" in sql:
            columns = ["geolocation_state", "total_net_revenue"]
            rows = [["CA", 910000], ["NY", 760000], ["TX", 620000]]
            summary = "California leads net revenue in the stubbed e-commerce result set."
        else:
            columns = ["customer_segment", "total_net_revenue"]
            rows = [["Enterprise", 1240000], ["Consumer", 830000], ["Small Business", 410000]]
            summary = "Enterprise leads net revenue in the stubbed e-commerce result set."
        result = ResultPayload(columns=columns, rows=rows, row_count=len(rows))
        shape = ResultShape(
            columns=result.columns,
            chart_type=ChartType.bar,
            row_count=result.row_count,
            aggregate_summary=summary,
        )
        return result, shape


class FakeChartSelector:
    def select(self, result: ResultPayload) -> tuple[ChartType, str]:
        dimension = result.columns[0] if result.columns else "dimension"
        return ChartType.bar, f"Showing as bar chart - categorical comparison detected on {dimension}."


class FakeStoryteller:
    async def summarize(self, result_shape: ResultShape, user_query: str) -> str:
        return result_shape.aggregate_summary


def clarification_options_for_signal() -> tuple[str, list[str]]:
    return (
        "Which revenue metric did you mean?",
        ["Gross revenue", "Net revenue", "Recognized revenue"],
    )


def metric_column(value: str) -> str:
    return _metric_column(value)


def _metric_column(value: str) -> str:
    lowered = value.lower()
    if "gross" in lowered:
        return "gross_revenue"
    if "recognized" in lowered or "recognised" in lowered:
        return "net_revenue"
    if "net" in lowered:
        return "net_revenue"
    return "net_revenue"


def _dimension_column(value: str) -> str:
    lowered = value.lower()
    if "state" in lowered or "geograph" in lowered or "region" in lowered:
        return "geolocation_state"
    if "category" in lowered or "product" in lowered:
        return "product_category_name"
    return "customer_segment"


def _revenue_expression(metric: str) -> str:
    net = "order_items.price * (1 - order_items.discount_rate) + order_items.freight_value"
    if metric == "gross_revenue":
        return "order_items.price + order_items.freight_value"
    return net


def _revenue_sql(metric: str, dimension: str) -> str:
    expression = _revenue_expression(metric)
    joins = [
        "JOIN orders ON order_items.order_id = orders.order_id",
        "JOIN customers ON orders.customer_id = customers.customer_id",
    ]
    if dimension == "geolocation_state":
        select_dimension = "geolocation.geolocation_state"
        joins.append(
            "JOIN geolocation ON customers.customer_zip_code_prefix = geolocation.zip_code_prefix"
        )
    elif dimension == "product_category_name":
        select_dimension = "products.product_category_name"
        joins.append("JOIN products ON order_items.product_id = products.product_id")
    else:
        select_dimension = "customers.customer_segment"
    return (
        f"SELECT {select_dimension} AS {dimension}, "
        f"SUM({expression}) AS total_{metric} "
        "FROM order_items "
        f"{' '.join(joins)} "
        "WHERE orders.order_status = 'delivered' "
        f"GROUP BY {select_dimension} "
        f"ORDER BY total_{metric} DESC "
        "LIMIT 100"
    )
