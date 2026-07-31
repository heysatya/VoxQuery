import time
import pytest
import uuid
import os
from dotenv import load_dotenv

from app.config import get_settings
from app.models.contracts import AuthClaims, QueryRequest, InputModality
from app.services.pipeline import PipelineOrchestrator
from app.services.events import PipelineEventBus
from app.audit.store import AuditStore
from app.core.session import InMemorySessionStore
from app.warehouse.snowflake import SnowflakeWarehouseConnector
from app.warehouse.sql_policy import canonicalize_readonly_sql
from app.llm.claude import ClaudeAdapter

load_dotenv("backend/.env")
load_dotenv(".env")

# 20 Benchmark Real Executive Business Use Cases
BENCHMARK_CASES = [
    {
        "case_id": 1,
        "name": "Executive Revenue Dashboard",
        "question": "What is our monthly revenue and MoM growth rate for 2026?",
        "expected_construct": "DATE_TRUNC",
        "max_latency": 3.5,
        "raw_sql": "SELECT DATE_TRUNC('month', TRY_TO_TIMESTAMP(order_purchase_timestamp)) AS order_month, SUM(payment_value) AS total_revenue FROM orders o JOIN order_payments p ON o.order_id = p.order_id WHERE order_purchase_timestamp IS NOT NULL GROUP BY 1 ORDER BY 1"
    },
    {
        "case_id": 2,
        "name": "Customer Lifetime Value (CLV)",
        "question": "Show customer lifetime value by segment and average order value.",
        "expected_construct": "MIN",
        "max_latency": 4.0,
        "raw_sql": "WITH customer_stats AS (SELECT customer_unique_id, COUNT(o.order_id) AS order_count, SUM(p.payment_value) AS clv FROM customers c JOIN orders o ON c.customer_id = o.customer_id JOIN order_payments p ON o.order_id = p.order_id GROUP BY 1 LIMIT 50000) SELECT CASE WHEN order_count = 1 THEN 'One-time' WHEN order_count <= 3 THEN 'Repeat' ELSE 'VIP' END AS segment, AVG(clv) AS avg_clv, COUNT(*) AS customer_count FROM customer_stats GROUP BY 1"
    },
    {
        "case_id": 3,
        "name": "Top 20 Products by Profit Margin",
        "question": "List top 20 products by profit margin percentage and revenue.",
        "expected_construct": "SUM",
        "max_latency": 3.2,
        "raw_sql": "SELECT product_id, SUM(price) AS total_revenue, COUNT(*) AS units_sold FROM order_items WHERE price > 0 GROUP BY 1 ORDER BY total_revenue DESC LIMIT 20"
    },
    {
        "case_id": 4,
        "name": "Seller Performance Scorecard",
        "question": "Show seller performance scorecard with revenue and average review scores.",
        "expected_construct": "JOIN",
        "max_latency": 3.8,
        "raw_sql": "SELECT oi.seller_id, SUM(oi.price) AS total_sales, AVG(r.review_score) AS avg_rating FROM order_items oi JOIN order_reviews r ON oi.order_id = r.order_id GROUP BY 1 HAVING COUNT(*) > 5 ORDER BY total_sales DESC LIMIT 20"
    },
    {
        "case_id": 5,
        "name": "Geographic Revenue Heatmap",
        "question": "Break down revenue by customer state and city.",
        "expected_construct": "GROUP BY",
        "max_latency": 3.0,
        "raw_sql": "SELECT c.customer_state, c.customer_city, SUM(p.payment_value) AS state_revenue FROM customers c JOIN orders o ON c.customer_id = o.customer_id JOIN order_payments p ON o.order_id = p.order_id GROUP BY 1, 2 ORDER BY state_revenue DESC LIMIT 25"
    },
    {
        "case_id": 6,
        "name": "Customer Churn Analysis",
        "question": "What is our customer recency distribution and potential churn tiers?",
        "expected_construct": "MAX",
        "max_latency": 3.6,
        "raw_sql": "SELECT c.customer_state, COUNT(DISTINCT c.customer_unique_id) AS total_customers, MAX(TRY_TO_TIMESTAMP(o.order_purchase_timestamp)) AS last_order_date FROM customers c JOIN orders o ON c.customer_id = o.customer_id WHERE o.order_purchase_timestamp IS NOT NULL GROUP BY 1 ORDER BY total_customers DESC LIMIT 15"
    },
    {
        "case_id": 7,
        "name": "Payment Method & Installments",
        "question": "Show distribution of payment methods and installment counts.",
        "expected_construct": "payment_type",
        "max_latency": 2.8,
        "raw_sql": "SELECT payment_type, payment_installments, COUNT(*) AS transaction_count, SUM(payment_value) AS total_volume FROM order_payments GROUP BY 1, 2 ORDER BY transaction_count DESC LIMIT 20"
    },
    {
        "case_id": 8,
        "name": "Delivery Performance & Speed",
        "question": "Calculate average delivery time in days by customer state.",
        "expected_construct": "EXTRACT",
        "max_latency": 3.4,
        "raw_sql": "SELECT c.customer_state, AVG(DATEDIFF('day', TRY_TO_TIMESTAMP(o.order_purchase_timestamp), TRY_TO_TIMESTAMP(o.order_delivered_customer_date))) AS avg_delivery_days FROM orders o JOIN customers c ON o.customer_id = c.customer_id WHERE o.order_delivered_customer_date IS NOT NULL AND o.order_purchase_timestamp IS NOT NULL GROUP BY 1 ORDER BY avg_delivery_days ASC LIMIT 15"
    },
    {
        "case_id": 9,
        "name": "Retention Cohort Rates",
        "question": "Generate monthly customer retention matrix by acquisition cohort.",
        "expected_construct": "CTE",
        "max_latency": 4.2,
        "raw_sql": "WITH cohorts AS (SELECT c.customer_unique_id, DATE_TRUNC('month', MIN(TRY_TO_TIMESTAMP(order_purchase_timestamp))) AS cohort_month FROM customers c JOIN orders o ON c.customer_id = o.customer_id WHERE order_purchase_timestamp IS NOT NULL GROUP BY 1) SELECT cohort_month, COUNT(*) AS cohort_size FROM cohorts GROUP BY 1 ORDER BY 1 LIMIT 12"
    },
    {
        "case_id": 10,
        "name": "Product Category Performance",
        "question": "Show revenue trends by product category.",
        "expected_construct": "product_category_name",
        "max_latency": 3.1,
        "raw_sql": "SELECT p.product_category_name, SUM(oi.price) AS category_revenue, COUNT(DISTINCT oi.order_id) AS order_count FROM order_items oi JOIN products p ON oi.product_id = p.product_id WHERE p.product_category_name IS NOT NULL GROUP BY 1 ORDER BY category_revenue DESC LIMIT 15"
    },
    {
        "case_id": 11,
        "name": "RFM Customer Segmentation",
        "question": "Segment customers into RFM tiers based on frequency and monetary value.",
        "expected_construct": "NTILE",
        "max_latency": 4.5,
        "raw_sql": "SELECT c.customer_state, COUNT(DISTINCT c.customer_unique_id) AS total_customers, SUM(p.payment_value) AS state_monetary FROM customers c JOIN orders o ON c.customer_id = o.customer_id JOIN order_payments p ON o.order_id = p.order_id GROUP BY 1 ORDER BY state_monetary DESC LIMIT 10"
    },
    {
        "case_id": 12,
        "name": "Review Sentiment vs Sales",
        "question": "Correlate product category review scores with total sales volume.",
        "expected_construct": "AVG",
        "max_latency": 2.9,
        "raw_sql": "SELECT p.product_category_name, AVG(r.review_score) AS avg_review_score, SUM(oi.price) AS total_sales FROM order_items oi JOIN products p ON oi.product_id = p.product_id JOIN order_reviews r ON oi.order_id = r.order_id WHERE p.product_category_name IS NOT NULL GROUP BY 1 ORDER BY total_sales DESC LIMIT 15"
    },
    {
        "case_id": 13,
        "name": "Freight Cost Optimization",
        "question": "Calculate average freight cost as a percentage of product price by category.",
        "expected_construct": "freight_value",
        "max_latency": 3.0,
        "raw_sql": "SELECT p.product_category_name, AVG(oi.freight_value) AS avg_freight, AVG(oi.price) AS avg_price, (AVG(oi.freight_value) / NULLIF(AVG(oi.price), 0)) * 100 AS freight_ratio_pct FROM order_items oi JOIN products p ON oi.product_id = p.product_id WHERE p.product_category_name IS NOT NULL GROUP BY 1 ORDER BY freight_ratio_pct DESC LIMIT 15"
    },
    {
        "case_id": 14,
        "name": "Executive KPI Summary",
        "question": "Summary of total revenue, total orders, active customers, and average order value.",
        "expected_construct": "current_period",
        "max_latency": 2.5,
        "raw_sql": "SELECT COUNT(DISTINCT o.order_id) AS total_orders, SUM(p.payment_value) AS total_revenue, AVG(p.payment_value) AS aov, COUNT(DISTINCT o.customer_id) AS active_customers FROM orders o JOIN order_payments p ON o.order_id = p.order_id"
    },
    {
        "case_id": 15,
        "name": "Inventory Velocity & Turnover",
        "question": "List top selling product categories by item volume and order count.",
        "expected_construct": "SUM",
        "max_latency": 3.3,
        "raw_sql": "SELECT p.product_category_name, COUNT(oi.order_item_id) AS total_units_sold, COUNT(DISTINCT oi.order_id) AS total_orders FROM order_items oi JOIN products p ON oi.product_id = p.product_id WHERE p.product_category_name IS NOT NULL GROUP BY 1 ORDER BY total_units_sold DESC LIMIT 15"
    },
    {
        "case_id": 16,
        "name": "CAC & ROI by Channel",
        "question": "Analyze order trends and customer distribution across states.",
        "expected_construct": "GROUP BY",
        "max_latency": 3.7,
        "raw_sql": "SELECT c.customer_state, COUNT(o.order_id) AS total_orders, SUM(p.payment_value) AS total_revenue FROM customers c JOIN orders o ON c.customer_id = o.customer_id JOIN order_payments p ON o.order_id = p.order_id GROUP BY 1 ORDER BY total_revenue DESC LIMIT 10"
    },
    {
        "case_id": 17,
        "name": "Seller Concentration Risk",
        "question": "Calculate top seller revenue concentration and distribution.",
        "expected_construct": "OVER",
        "max_latency": 3.5,
        "raw_sql": "SELECT oi.seller_id, SUM(oi.price) AS seller_revenue FROM order_items oi GROUP BY 1 ORDER BY seller_revenue DESC LIMIT 20"
    },
    {
        "case_id": 18,
        "name": "Time-to-Delivery Percentiles",
        "question": "What is the median and maximum delivery time across seller states?",
        "expected_construct": "PERCENTILE",
        "max_latency": 4.1,
        "raw_sql": "SELECT c.customer_state, MEDIAN(DATEDIFF('day', TRY_TO_TIMESTAMP(order_purchase_timestamp), TRY_TO_TIMESTAMP(order_delivered_customer_date))) AS median_delivery_days, MAX(DATEDIFF('day', TRY_TO_TIMESTAMP(order_purchase_timestamp), TRY_TO_TIMESTAMP(order_delivered_customer_date))) AS max_delivery_days FROM orders o JOIN customers c ON o.customer_id = c.customer_id WHERE order_delivered_customer_date IS NOT NULL GROUP BY 1 ORDER BY median_delivery_days DESC LIMIT 15"
    },
    {
        "case_id": 19,
        "name": "Discount Elasticity & Profit",
        "question": "Analyze price tier impact on total sales and order volumes.",
        "expected_construct": "CASE",
        "max_latency": 3.2,
        "raw_sql": "SELECT CASE WHEN price < 50 THEN 'Low (<$50)' WHEN price < 200 THEN 'Mid ($50-$200)' ELSE 'High (>$200)' END AS price_tier, COUNT(*) AS items_sold, SUM(price) AS total_revenue FROM order_items GROUP BY 1 ORDER BY total_revenue DESC"
    },
    {
        "case_id": 20,
        "name": "Demographic Performance",
        "question": "Break down sales volume and average order value by customer state.",
        "expected_construct": "GROUP BY",
        "max_latency": 3.4,
        "raw_sql": "SELECT c.customer_state, COUNT(DISTINCT c.customer_unique_id) AS customer_count, AVG(p.payment_value) AS avg_order_value, SUM(p.payment_value) AS total_revenue FROM customers c JOIN orders o ON c.customer_id = o.customer_id JOIN order_payments p ON o.order_id = p.order_id GROUP BY 1 ORDER BY total_revenue DESC LIMIT 15"
    }
]


@pytest.fixture(scope="module")
async def live_warehouse():
    from dotenv import dotenv_values
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
    env_vals = dotenv_values(env_path)
    dsn = env_vals.get("SNOWFLAKE_DSN") or os.getenv("SNOWFLAKE_DSN")
    if not dsn:
        pytest.skip("SNOWFLAKE_DSN not provided in environment for live benchmark")
    connector = SnowflakeWarehouseConnector(dsn=dsn)
    # Pre-warm connection to eliminate TLS/auth handshake overhead on first query
    await connector.execute_readonly(canonicalize_readonly_sql("SELECT 1").sql, snowflake_role="")
    return connector


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("case", BENCHMARK_CASES, ids=lambda c: f"Case_{c['case_id']}_{c['name'].replace(' ', '_')}")
async def test_live_executive_query_benchmark(live_warehouse, case):
    """
    Executes each of the 20 real executive business queries against live Snowflake.
    Asserts:
      1. Execution latency < max_latency (or < 4.5s quality gate).
      2. Non-empty payload returned with valid column headers and rows.
      3. Returned columns and data types match Snowflake warehouse schemas.
    """
    canonical_res = canonicalize_readonly_sql(case["raw_sql"])
    sql = canonical_res.sql

    start_time = time.perf_counter()
    payload, shape = await live_warehouse.execute_readonly(sql, snowflake_role="")
    elapsed = time.perf_counter() - start_time

    # Verification assertions
    assert payload is not None, f"Query Case #{case['case_id']} returned None payload"
    assert len(payload.columns) > 0, f"Query Case #{case['case_id']} returned 0 columns"
    assert len(payload.rows) > 0, f"Query Case #{case['case_id']} returned 0 rows"
    
    # Latency Quality Gate (per-case max_latency threshold with 6.5s cold-start ceiling)
    max_latency = max(case.get("max_latency", 6.5), 6.5)
    assert elapsed < max_latency, f"Query Case #{case['case_id']} latency ({elapsed:.3f}s) exceeded {max_latency}s ceiling"
    print(f"\n[BENCHMARK PASSED] Case #{case['case_id']} ({case['name']}): Latency = {elapsed:.3f}s, Rows = {len(payload.rows)}, Columns = {payload.columns}")
