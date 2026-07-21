import os
from pathlib import Path

import asyncpg

_DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"

async def run_migrations(dsn: str, migrations_dir: Path | None = None) -> None:
    target_dir = migrations_dir or _DEFAULT_MIGRATIONS_DIR
    
    if not target_dir.exists() or not target_dir.is_dir():
        raise RuntimeError(f"MIGRATIONS_DIR does not exist or is not a directory: {target_dir}")

    conn = await asyncpg.connect(dsn, statement_cache_size=0)
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
            
        migrations = sorted([f for f in os.listdir(target_dir) if f.endswith(".sql")])
        for migration in migrations:
            if migration not in applied:
                print(f"Applying {migration}...")
                with open(target_dir / migration, "r", encoding="utf-8") as f:
                    sql = f.read()
                
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute(
                        "INSERT INTO schema_migrations (version) VALUES ($1)",
                        migration
                    )
    finally:
        await conn.close()
