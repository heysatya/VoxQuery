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
                file_path = target_dir / migration
                # Read as bytes first and attempt multiple decodings to handle
                # migrations saved with different encodings (UTF-8, UTF-16, etc.).
                with open(file_path, "rb") as bf:
                    data = bf.read()
                try:
                    sql = data.decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        # Let Python handle byte-order mark with 'utf-16'
                        sql = data.decode("utf-16")
                    except UnicodeDecodeError:
                        # Last-resort fallback preserves bytes as-is so migration can still run.
                        sql = data.decode("latin-1")
                        print(f"Warning: migration {migration} decoded with latin-1 fallback; please convert to UTF-8")

                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute(
                        "INSERT INTO schema_migrations (version) VALUES ($1)", migration
                    )
    finally:
        await conn.close()
