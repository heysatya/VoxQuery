import os
import asyncio
import uuid
import asyncpg
from openai import AsyncOpenAI
from dotenv import load_dotenv

# We need to import the connector to fetch the schema
# Adjust sys.path so we can import from app
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.warehouse.snowflake import SnowflakeWarehouseConnector

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


async def sync_schema():
    dsn = os.getenv("SNOWFLAKE_DSN")
    supabase_url = os.getenv("SUPABASE_DATABASE_URL")
    openai_key = os.getenv("OPENAI_API_KEY")

    if not dsn or dsn == "dummy_dsn":
        raise ValueError("Valid SNOWFLAKE_DSN is required.")
    if not supabase_url:
        raise ValueError("SUPABASE_DATABASE_URL is required.")
    if not openai_key:
        raise ValueError("OPENAI_API_KEY is required.")

    print("1. Fetching schema snapshot from live Snowflake...")
    connector = SnowflakeWarehouseConnector(dsn)
    schema_tables = connector.fetch_schema_snapshot()

    print(f"   -> Found {len(schema_tables)} tables in Snowflake.")

    # ---------------------------------------------------------
    # Schema Drift Logging
    # ---------------------------------------------------------
    import json

    current_schema = {}
    for table in schema_tables:
        current_schema[table.table_name] = [col.name for col in table.columns]

    last_schema_path = os.path.join(os.path.dirname(__file__), "schema_snapshot_last.json")
    if os.path.exists(last_schema_path):
        with open(last_schema_path, "r", encoding="utf-8") as f:
            last_schema = json.load(f)

        added_tables = set(current_schema.keys()) - set(last_schema.keys())
        removed_tables = set(last_schema.keys()) - set(current_schema.keys())

        drift_detected = False
        if added_tables:
            print(f"   -> DRIFT ALER: Added tables: {', '.join(added_tables)}")
            drift_detected = True
        if removed_tables:
            print(f"   -> DRIFT ALERT: Removed tables: {', '.join(removed_tables)}")
            drift_detected = True

        for t_name in current_schema.keys():
            if t_name in last_schema:
                added_cols = set(current_schema[t_name]) - set(last_schema[t_name])
                removed_cols = set(last_schema[t_name]) - set(current_schema[t_name])
                if added_cols:
                    print(
                        f"   -> DRIFT ALERT: Table {t_name} added columns: {', '.join(added_cols)}"
                    )
                    drift_detected = True
                if removed_cols:
                    print(
                        f"   -> DRIFT ALERT: Table {t_name} removed columns: {', '.join(removed_cols)}"
                    )
                    drift_detected = True

        if not drift_detected:
            print("   -> No schema drift detected since last run.")

    with open(last_schema_path, "w", encoding="utf-8") as f:
        json.dump(current_schema, f, indent=2)
    # ---------------------------------------------------------

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tenant-id",
        type=str,
        default="00000000-0000-0000-0000-000000000101",
        help="Tenant ID to provision the schema and DSN for.",
    )
    args, unknown = parser.parse_known_args()

    tenant_id = args.tenant_id

    print("2. Connecting to Supabase...")
    # Fix pgbouncer connection issue if needed by stripping it for asyncpg or using prepared statements safely
    conn = await asyncpg.connect(supabase_url, statement_cache_size=0)

    try:
        # Ensure the tenant exists
        await conn.execute(
            "INSERT INTO tenants (id, name) VALUES ($1, 'Pilot Sandbox Tenant') ON CONFLICT (id) DO NOTHING;",
            tenant_id,
        )

        print(f"   -> Using Tenant ID: {tenant_id}")

        # Store encrypted DSN in tenant_connections
        fernet_key = os.getenv("FERNET_KEY")
        if fernet_key:
            try:
                from cryptography.fernet import Fernet

                f = Fernet(fernet_key.encode())
                encrypted_dsn = f.encrypt(dsn.encode()).decode()
                await conn.execute(
                    """
                    INSERT INTO tenant_connections (tenant_id, snowflake_dsn)
                    VALUES ($1, $2)
                    ON CONFLICT (tenant_id) DO UPDATE SET snowflake_dsn = $2;
                """,
                    tenant_id,
                    encrypted_dsn,
                )
                print("   -> Stored encrypted DSN in tenant_connections.")
            except Exception as e:
                print(f"   -> Warning: Failed to encrypt and store DSN: {e}")
        else:
            print("   -> Warning: FERNET_KEY not set. Cannot populate tenant_connections table.")

        import json

        # from app.rag.query_rewriter import METRIC_SYNONYMS, TABLE_SYNONYMS
        from app.rag.glossary_defaults import DEFAULT_METRIC_SYNONYMS, DEFAULT_TABLE_SYNONYMS

        try:
            await conn.execute(
                """
                INSERT INTO tenant_glossary (tenant_id, metric_synonyms, table_synonyms)
                VALUES ($1, $2, $3)
                ON CONFLICT (tenant_id) DO UPDATE SET 
                    metric_synonyms = $2,
                    table_synonyms = $3,
                    updated_at = now();
            """,
                tenant_id,
                json.dumps(DEFAULT_METRIC_SYNONYMS),
                json.dumps(DEFAULT_TABLE_SYNONYMS),
            )
            print("   -> Stored default business glossary in tenant_glossary.")
        except Exception as e:
            print(f"   -> Warning: Failed to populate tenant_glossary: {e}")

        # Clear existing chunks for this tenant
        await conn.execute("DELETE FROM schema_chunks WHERE tenant_id = $1;", tenant_id)

        print("3. Generating embeddings and syncing to pgvector...")
        openai = AsyncOpenAI(api_key=openai_key)
        table_synonyms = {
            "ORDERS": ["orders", "purchases", "transactions", "sales"],
            "ORDER_ITEMS": ["items", "line items", "order details", "products ordered"],
            "CUSTOMERS": ["customers", "buyers", "clients", "users"],
            "PRODUCTS": ["products", "catalog", "inventory", "items", "skus"],
            "SELLERS": ["sellers", "vendors", "suppliers", "merchants"],
            "ORDER_REVIEWS": ["reviews", "ratings", "feedback", "satisfaction"],
            "ORDER_PAYMENTS": ["payments", "payment methods", "billing"],
            "GEOLOCATION": ["location", "region", "geography", "state", "city"],
        }
        table_related_metrics = {
            "ORDERS": [
                "revenue",
                "order_count",
                "average_order_value",
                "active_customers",
                "discount_rate",
            ],
            "ORDER_ITEMS": [
                "units_sold",
                "product_revenue",
                "profit",
                "profit_margin",
                "revenue",
                "average_order_value",
            ],
            "CUSTOMERS": ["active_customers", "customer_lifetime_value", "churn_risk", "rfm"],
            "PRODUCTS": ["product_revenue", "units_sold", "profit_margin"],
            "SELLERS": ["late_deliveries", "seller_performance", "freight_cost"],
            "ORDER_REVIEWS": ["customer_satisfaction_score"],
            "ORDER_PAYMENTS": ["payment_methods"],
            "GEOLOCATION": ["geographic_revenue", "revenue"],
        }

        inserted_count = 0
        for table in schema_tables:
            # Create embedding for the table itself
            col_list_str = ", ".join([f"{col.name} ({col.data_type})" for col in table.columns])
            syns = table_synonyms.get(table.table_name, [])
            syns_str = f"\nAlso known as: {', '.join(syns)}" if syns else ""
            rel_metrics = table_related_metrics.get(table.table_name, [])
            rel_metrics_str = f"\nRelated metrics: {', '.join(rel_metrics)}" if rel_metrics else ""
            table_content = f"Table: {table.table_name}\nColumns: {col_list_str}\nKeywords: {table.table_name.lower()} data{syns_str}{rel_metrics_str}"
            response = await openai.embeddings.create(
                input=table_content, model="text-embedding-3-small"
            )
            table_embedding = response.data[0].embedding

            await conn.execute(
                """
                INSERT INTO schema_chunks (id, tenant_id, table_name, column_name, content, source_ref, entity_type, embedding)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector)
            """,
                uuid.uuid4(),
                tenant_id,
                table.table_name,
                None,
                table_content,
                f"snowflake://{table.table_name}",
                "table",
                str(table_embedding),
            )
            inserted_count += 1

            # Create embedding for each column
            for col in table.columns:
                col_content = (
                    f"Table: {table.table_name}, Column: {col.name} (Type: {col.data_type})"
                )
                c_response = await openai.embeddings.create(
                    input=col_content, model="text-embedding-3-small"
                )
                c_embedding = c_response.data[0].embedding

                await conn.execute(
                    """
                    INSERT INTO schema_chunks (id, tenant_id, table_name, column_name, content, source_ref, entity_type, embedding)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector)
                """,
                    uuid.uuid4(),
                    tenant_id,
                    table.table_name,
                    col.name,
                    col_content,
                    f"snowflake://{table.table_name}.{col.name}",
                    "column",
                    str(c_embedding),
                )
                inserted_count += 1

        print("4. Skipping YAML metrics (metrics moved to tenant glossary)...")

        print("5. Adding basic business rules...")
        business_rules = [
            (
                "completed_orders_only",
                "Always filter ORDERS with WHERE order_status = 'delivered'.",
                "orders, sales, delivery",
                "revenue, order_count",
                "ORDERS",
            ),
            (
                "revenue_net_of_discounts",
                "Net revenue: price * (1 - discount_rate). Never use raw price.",
                "revenue, sales, profit",
                "revenue",
                "ORDER_ITEMS",
            ),
            (
                "duckdb_date_syntax",
                "DuckDB: DATE_TRUNC('month', col), CURRENT_DATE - INTERVAL '30 days', DATEDIFF('day', start, end)",
                "date, time, trend, monthly, yearly",
                "all",
                "all",
            ),
            (
                "snowflake_date_syntax",
                "Use Snowflake date syntax: DATEADD('day', -30, CURRENT_DATE()), DATE_TRUNC('month', TRY_TO_TIMESTAMP(col)), DATEDIFF('day', TRY_TO_TIMESTAMP(start), TRY_TO_TIMESTAMP(end)). Note: Always use TRY_TO_TIMESTAMP(col) inside DATE_TRUNC/DATEADD/DATEDIFF if column type is VARCHAR.",
                "date, time, trend, monthly, yearly",
                "all",
                "all",
            ),
            (
                "customer_geolocation_join",
                "Join CUSTOMERS to GEOLOCATION on customer_zip_code_prefix = geolocation_zip_code_prefix.",
                "customers, location, city, state, zip",
                "all",
                "CUSTOMERS, GEOLOCATION",
            ),
            (
                "profit_calculation",
                "Profit is calculated as (price - freight_value).",
                "profit, cost, freight",
                "profit_margin, total_profit",
                "ORDER_ITEMS",
            ),
            (
                "delivery_time_calculation",
                "Delivery time is DATEDIFF('day', order_purchase_timestamp, order_delivered_customer_date).",
                "delivery, late, time, days",
                "late_deliveries",
                "ORDERS",
            ),
        ]
        for rule_name, rule_text, rule_keywords, applies_metrics, applies_tables in business_rules:
            rule_content = f"Business Rule: {rule_name}\nRule: {rule_text}\nKeywords: {rule_keywords}\nApplies to metrics: {applies_metrics}\nApplies to tables: {applies_tables}"
            response = await openai.embeddings.create(
                input=rule_content, model="text-embedding-3-small"
            )
            r_embedding = response.data[0].embedding

            await conn.execute(
                """
                INSERT INTO schema_chunks (id, tenant_id, table_name, column_name, content, source_ref, entity_type, embedding)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector)
            """,
                uuid.uuid4(),
                tenant_id,
                "global",
                None,
                rule_content,
                f"rule://{rule_name}",
                "rule",
                str(r_embedding),
            )
            inserted_count += 1

        print(f"Success: Successfully synced {inserted_count} schema chunks to Supabase!")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(sync_schema())
