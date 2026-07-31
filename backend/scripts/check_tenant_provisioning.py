import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, asdict

import asyncpg
from cryptography.fernet import Fernet
from dotenv import load_dotenv


load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


@dataclass
class CheckResult:
    name: str
    ok: bool
    required: bool
    detail: str


def _result(name: str, ok: bool, detail: str, *, required: bool = True) -> CheckResult:
    return CheckResult(name=name, ok=ok, required=required, detail=detail)


async def _fetch_count(conn: asyncpg.Connection, sql: str, tenant_id: str) -> int:
    value = await conn.fetchval(sql, tenant_id)
    return int(value or 0)


async def check_tenant(tenant_id: str) -> list[CheckResult]:
    db_url = os.getenv("SUPABASE_DATABASE_URL")
    fernet_key = os.getenv("FERNET_KEY")
    results: list[CheckResult] = []

    if not db_url:
        return [_result("database_configured", False, "SUPABASE_DATABASE_URL is not set")]

    if not fernet_key:
        results.append(_result("fernet_key_configured", False, "FERNET_KEY is not set"))
        fernet = None
    else:
        try:
            fernet = Fernet(fernet_key.encode())
            results.append(_result("fernet_key_configured", True, "FERNET_KEY is syntactically valid"))
        except Exception as exc:
            results.append(_result("fernet_key_configured", False, f"FERNET_KEY is invalid: {type(exc).__name__}"))
            fernet = None

    try:
        conn = await asyncpg.connect(db_url, statement_cache_size=0)
    except Exception as exc:
        results.append(_result("database_connected", False, f"Database connection failed: {type(exc).__name__}"))
        return results

    results.append(_result("database_connected", True, "Connected to Supabase Postgres"))

    try:
        tenant_exists = await conn.fetchval("SELECT EXISTS(SELECT 1 FROM tenants WHERE id = $1)", tenant_id)
        results.append(_result("tenant_exists", bool(tenant_exists), f"tenant_id={tenant_id}"))

        connection_row = await conn.fetchrow(
            "SELECT snowflake_dsn FROM tenant_connections WHERE tenant_id = $1",
            tenant_id,
        )
        results.append(
            _result(
                "tenant_connection_exists",
                connection_row is not None,
                "tenant_connections row found" if connection_row else "tenant_connections row missing",
            )
        )

        if connection_row and fernet:
            try:
                decrypted = fernet.decrypt(str(connection_row["snowflake_dsn"]).encode()).decode()
                has_snowflake_scheme = decrypted.startswith("snowflake://")
                results.append(
                    _result(
                        "tenant_connection_decrypts",
                        has_snowflake_scheme,
                        "Decrypted DSN has snowflake:// scheme"
                        if has_snowflake_scheme
                        else "Decrypted value does not look like a Snowflake DSN",
                    )
                )
            except Exception as exc:
                results.append(
                    _result(
                        "tenant_connection_decrypts",
                        False,
                        f"Stored DSN cannot be decrypted with current FERNET_KEY: {type(exc).__name__}",
                    )
                )
        else:
            results.append(
                _result(
                    "tenant_connection_decrypts",
                    False,
                    "Skipped because tenant connection or valid FERNET_KEY is missing",
                )
            )

        schema_chunks = await _fetch_count(
            conn,
            "SELECT count(*) FROM schema_chunks WHERE tenant_id = $1",
            tenant_id,
        )
        results.append(
            _result(
                "schema_chunks_populated",
                schema_chunks > 0,
                f"{schema_chunks} schema_chunks rows found",
            )
        )

        glossary_exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM tenant_glossary WHERE tenant_id = $1)",
            tenant_id,
        )
        results.append(_result("tenant_glossary_exists", bool(glossary_exists), f"tenant_id={tenant_id}"))

        memberships = await _fetch_count(
            conn,
            "SELECT count(*) FROM tenant_memberships WHERE tenant_id = $1 AND deleted_at IS NULL",
            tenant_id,
        )
        results.append(
            _result(
                "active_memberships_present",
                memberships > 0,
                f"{memberships} active tenant_memberships rows found",
                required=False,
            )
        )
    except Exception as exc:
        results.append(_result("schema_queries_completed", False, f"Provisioning query failed: {type(exc).__name__}"))
    finally:
        await conn.close()

    return results


def _print_text(tenant_id: str, results: list[CheckResult]) -> None:
    print(f"Tenant provisioning check: {tenant_id}")
    for item in results:
        label = "OK" if item.ok else ("WARN" if not item.required else "FAIL")
        required = "required" if item.required else "optional"
        print(f"[{label}] {item.name} ({required}) - {item.detail}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Check VoxQuery tenant provisioning for a Clerk org ID.")
    parser.add_argument("--tenant-id", required=True, help="Clerk Organization ID, for example org_...")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()

    results = await check_tenant(args.tenant_id)
    failed_required = [item for item in results if item.required and not item.ok]

    if args.json:
        print(
            json.dumps(
                {
                    "tenant_id": args.tenant_id,
                    "ok": not failed_required,
                    "results": [asdict(item) for item in results],
                },
                indent=2,
            )
        )
    else:
        _print_text(args.tenant_id, results)

    return 1 if failed_required else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
