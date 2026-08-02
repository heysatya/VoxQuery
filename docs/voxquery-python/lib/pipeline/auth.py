import os
from dataclasses import dataclass
import httpx


@dataclass
class AuthResult:
    ok: bool
    user_id: str | None = None
    org_id: str | None = None  # used downstream for RLS-scoped queries in multi-tenant setups
    error: str | None = None


SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")


def verify_auth(authorization_header: str | None) -> AuthResult:
    """
    First checkpoint in the pipeline. Every other guardrail assumes this
    has already run. Uses a direct REST call to Supabase's auth endpoint
    with the anon key — NEVER the service_role key, which bypasses Row-Level
    Security entirely and must never touch a request path that handles
    arbitrary user-driven SQL.
    """
    if not authorization_header or not authorization_header.startswith("Bearer "):
        return AuthResult(ok=False, error="Missing or malformed Authorization header.")

    token = authorization_header[len("Bearer "):]

    try:
        response = httpx.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_ANON_KEY},
            timeout=5.0,
        )
    except httpx.HTTPError:
        return AuthResult(ok=False, error="Could not reach the authentication service. Please try again.")

    if response.status_code != 200:
        return AuthResult(ok=False, error="Invalid or expired session. Please sign in again.")

    user = response.json()
    return AuthResult(
        ok=True,
        user_id=user.get("id"),
        org_id=(user.get("app_metadata") or {}).get("org_id"),
    )
