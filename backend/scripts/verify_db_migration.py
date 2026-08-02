import asyncio
import os
from dotenv import load_dotenv
import asyncpg

load_dotenv("backend/.env")
load_dotenv(".env")

dsn = os.getenv("POSTGRES_DSN") or os.getenv("SUPABASE_DATABASE_URL")


async def verify():
    if not dsn:
        print("ERROR: POSTGRES_DSN / SUPABASE_DATABASE_URL is not set.")
        return False

    print("Connecting to PostgreSQL...")
    conn = await asyncpg.connect(dsn)
    tables = ["turns", "user_preferences", "pinned_widgets", "briefing_send_log"]
    found = {}

    for tbl in tables:
        query = "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = $1);"
        val = await conn.fetchval(query, tbl)
        found[tbl] = val

    await conn.close()

    print("\n==============================================")
    print("Database Migration Verification Results:")
    print("==============================================")
    all_present = True
    for tbl, exists in found.items():
        status = "PRESENT" if exists else "MISSING"
        if not exists:
            all_present = False
        print(f"  Table '{tbl}': {status}")
    print("==============================================")
    return all_present


if __name__ == "__main__":
    success = asyncio.run(verify())
    if not success:
        exit(1)
