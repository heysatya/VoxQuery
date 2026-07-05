import os
from pathlib import Path

import asyncpg

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "db" / "migrations"

async def run_migrations(dsn: str) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
        
        # Get all applied migrations
        applied = set(
            record["version"] 
            for record in await conn.fetch("SELECT version FROM schema_migrations")
        )
        
        if not MIGRATIONS_DIR.exists():
            return
            
        migrations = sorted([f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql")])
        for migration in migrations:
            if migration not in applied:
                print(f"Applying {migration}...")
                with open(MIGRATIONS_DIR / migration, "r", encoding="utf-8") as f:
                    sql = f.read()
                
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute(
                        "INSERT INTO schema_migrations (version) VALUES ($1)",
                        migration
                    )
    finally:
        await conn.close()
