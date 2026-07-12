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
        
        inserted_count = 0
        for table in schema_tables:
            # Create embedding for the table itself
            table_content = f"Table: {table.table_name}"
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
                
        print(f"Success: Successfully synced {inserted_count} schema chunks to Supabase!")
        
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(sync_schema())
