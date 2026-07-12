import os
import asyncio
import uuid
import asyncpg
from openai import AsyncOpenAI
from dotenv import load_dotenv

# We need to import the connector to fetch the schema
# Adjust sys.path so we can import from app
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.warehouse.snowflake import SnowflakeWarehouseConnector

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

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
    
    print("2. Connecting to Supabase...")
    # Fix pgbouncer connection issue if needed by stripping it for asyncpg or using prepared statements safely
    conn = await asyncpg.connect(supabase_url, statement_cache_size=0)
    
    try:
        # Get a valid tenant_id
        tenant_row = await conn.fetchrow("SELECT id FROM tenants LIMIT 1;")
        if not tenant_row:
            # Create a dummy tenant if none exists
            tenant_id = uuid.uuid4()
            await conn.execute("INSERT INTO tenants (id, name) VALUES ($1, 'Default Sandbox Tenant') ON CONFLICT (id) DO NOTHING;", tenant_id)
        else:
            tenant_id = tenant_row['id']
            
        print(f"   -> Using Tenant ID: {tenant_id}")
        
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
            "ORDERS": ["revenue", "order_count", "average_order_value", "active_customers", "discount_rate"],
            "ORDER_ITEMS": ["units_sold", "product_revenue", "profit", "profit_margin", "revenue", "average_order_value"],
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
            response = await openai.embeddings.create(input=table_content, model="text-embedding-3-small")
            table_embedding = response.data[0].embedding
            
            await conn.execute("""
                INSERT INTO schema_chunks (id, tenant_id, table_name, column_name, content, source_ref, entity_type, embedding)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector)
            """, uuid.uuid4(), tenant_id, table.table_name, None, table_content, f"snowflake://{table.table_name}", "table", str(table_embedding))
            inserted_count += 1
            
            # Create embedding for each column
            for col in table.columns:
                col_content = f"Table: {table.table_name}, Column: {col.name} (Type: {col.data_type})"
                c_response = await openai.embeddings.create(input=col_content, model="text-embedding-3-small")
                c_embedding = c_response.data[0].embedding
                
                await conn.execute("""
                    INSERT INTO schema_chunks (id, tenant_id, table_name, column_name, content, source_ref, entity_type, embedding)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector)
                """, uuid.uuid4(), tenant_id, table.table_name, col.name, col_content, f"snowflake://{table.table_name}.{col.name}", "column", str(c_embedding))
                inserted_count += 1
                
        print("4. Syncing metrics from YAML...")
        from app.rag.metric_registry import MetricRegistry
        metrics_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'metrics.yaml')
        registry = MetricRegistry(metrics_path)
        metrics = registry.list_metrics()
        
        for metric in metrics:
            metric_content = metric.to_metric_text()
            response = await openai.embeddings.create(input=metric_content, model="text-embedding-3-small")
            m_embedding = response.data[0].embedding
            
            await conn.execute("""
                INSERT INTO schema_chunks (id, tenant_id, table_name, column_name, content, source_ref, entity_type, embedding)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector)
            """, uuid.uuid4(), tenant_id, metric.source_table or "global", None, metric_content, f"metric://{metric.name}", "metric", str(m_embedding))
            inserted_count += 1

        print("5. Adding basic business rules...")
        business_rules = [
            ("completed_orders_only", "Always filter ORDERS with WHERE order_status = 'delivered'.", "orders, sales, delivery", "revenue, order_count", "ORDERS"),
            ("revenue_net_of_discounts", "Net revenue: price * (1 - discount_rate). Never use raw price.", "revenue, sales, profit", "revenue", "ORDER_ITEMS"),
            ("duckdb_date_syntax", "DuckDB: DATE_TRUNC('month', col), CURRENT_DATE - INTERVAL '30 days', DATEDIFF('day', start, end)", "date, time, trend, monthly, yearly", "all", "all"),
            ("snowflake_date_syntax", "Use Snowflake date syntax: DATEADD('day', -30, CURRENT_DATE()), DATE_TRUNC('month', col), DATEDIFF('day', start, end)", "date, time, trend, monthly, yearly", "all", "all"),
            ("customer_geolocation_join", "Join CUSTOMERS to GEOLOCATION on customer_zip_code_prefix = geolocation_zip_code_prefix.", "customers, location, city, state, zip", "all", "CUSTOMERS, GEOLOCATION"),
            ("profit_calculation", "Profit is calculated as (price - freight_value).", "profit, cost, freight", "profit_margin, total_profit", "ORDER_ITEMS"),
            ("delivery_time_calculation", "Delivery time is DATEDIFF('day', order_purchase_timestamp, order_delivered_customer_date).", "delivery, late, time, days", "late_deliveries", "ORDERS")
        ]
        for rule_name, rule_text, rule_keywords, applies_metrics, applies_tables in business_rules:
            rule_content = f"Business Rule: {rule_name}\nRule: {rule_text}\nKeywords: {rule_keywords}\nApplies to metrics: {applies_metrics}\nApplies to tables: {applies_tables}"
            response = await openai.embeddings.create(input=rule_content, model="text-embedding-3-small")
            r_embedding = response.data[0].embedding
            
            await conn.execute("""
                INSERT INTO schema_chunks (id, tenant_id, table_name, column_name, content, source_ref, entity_type, embedding)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector)
            """, uuid.uuid4(), tenant_id, "global", None, rule_content, f"rule://{rule_name}", "rule", str(r_embedding))
            inserted_count += 1
                
        print(f"Success: Successfully synced {inserted_count} schema chunks to Supabase!")
        
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(sync_schema())
