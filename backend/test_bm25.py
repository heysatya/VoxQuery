import asyncio, asyncpg, os
from dotenv import load_dotenv
load_dotenv()

async def test():
    conn = await asyncpg.connect(os.environ['SUPABASE_DATABASE_URL'], statement_cache_size=0)
    tenant_id = (await conn.fetchrow('SELECT id FROM tenants LIMIT 1'))['id']
    query = 'revenue net sales topline income earnings gross revenue net revenue'
    rows = await conn.fetch("""
        SELECT source_ref, similarity FROM (
            SELECT source_ref, ts_rank(to_tsvector('english', content), to_tsquery('english', replace(plainto_tsquery('english', $1)::text, '&', '|'))) AS similarity
            FROM schema_chunks
            WHERE tenant_id = $2
              AND to_tsvector('english', content) @@ to_tsquery('english', replace(plainto_tsquery('english', $1)::text, '&', '|'))
        ) x ORDER BY similarity DESC LIMIT 5
    """, query, tenant_id)
    print(f'Rows found: {len(rows)}')
    for r in rows: print(dict(r))
    await conn.close()

asyncio.run(test())
