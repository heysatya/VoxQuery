-- Migration 012: Secure share links for turn results.
-- Tokens are never stored in plaintext; only the SHA-256 hash is persisted.
-- Shared results are snapshots, not live warehouse queries.

CREATE TABLE IF NOT EXISTS share_links (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    creator_user_id     TEXT NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
    turn_id             UUID NOT NULL REFERENCES turns(turn_id) ON DELETE CASCADE,
    -- SHA-256 hex digest of the opaque token; raw token is never stored
    token_hash          TEXT NOT NULL,
    -- optional human label for the link
    label               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at          TIMESTAMPTZ NOT NULL,
    -- NULL = not revoked; set to NOW() on revocation
    revoked_at          TIMESTAMPTZ,
    last_accessed_at    TIMESTAMPTZ,
    access_count        INTEGER NOT NULL DEFAULT 0 CHECK (access_count >= 0)
);

-- Token hash must be globally unique (tokens are opaque and not reusable)
CREATE UNIQUE INDEX IF NOT EXISTS uq_share_links_token_hash
    ON share_links (token_hash);

-- Efficient listing of active links per tenant+user
CREATE INDEX IF NOT EXISTS idx_share_links_tenant_user
    ON share_links (tenant_id, creator_user_id);

-- Link validity check: expiry and revocation lookups
CREATE INDEX IF NOT EXISTS idx_share_links_turn
    ON share_links (turn_id);

CREATE INDEX IF NOT EXISTS idx_share_links_expires_revoked
    ON share_links (expires_at, revoked_at);
