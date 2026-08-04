-- Migration 013: Durable per-user executive memory.
-- Stores explainable, user-scoped, tenant-scoped preferences and recurring interests.
-- Never stores raw warehouse rows or arbitrary data.

CREATE TABLE IF NOT EXISTS executive_memory (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id           TEXT NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
    -- memory_type: one of metric_interest, dimension_interest, time_range, filter_preference, clarification_resolution
    memory_type       TEXT NOT NULL CHECK (memory_type IN (
                          'metric_interest',
                          'dimension_interest',
                          'time_range',
                          'filter_preference',
                          'clarification_resolution'
                      )),
    -- normalized machine key, e.g. 'revenue', 'region', 'last_quarter'
    subject           TEXT NOT NULL,
    -- human-readable label shown to the user, e.g. 'Revenue (total_net_revenue)'
    label             TEXT NOT NULL,
    -- turn that first observed this preference
    source_turn_id    UUID REFERENCES turns(turn_id) ON DELETE SET NULL,
    -- session that first observed this preference (optional)
    source_session_id UUID REFERENCES sessions(session_id) ON DELETE SET NULL,
    -- 0.0–1.0 confidence from pipeline evidence
    confidence        DOUBLE PRECISION NOT NULL DEFAULT 0.8 CHECK (confidence >= 0.0 AND confidence <= 1.0),
    -- most recent observation
    last_observed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- soft-delete / archival; NULL = active
    archived_at       TIMESTAMPTZ
);

-- Prevent duplicate active memories for the same user+tenant+type+subject
CREATE UNIQUE INDEX IF NOT EXISTS uq_executive_memory_active
    ON executive_memory (tenant_id, user_id, memory_type, subject)
    WHERE archived_at IS NULL;

-- Efficient lookup of all active memories for a user within a tenant
CREATE INDEX IF NOT EXISTS idx_executive_memory_tenant_user
    ON executive_memory (tenant_id, user_id)
    WHERE archived_at IS NULL;

-- Source attribution index
CREATE INDEX IF NOT EXISTS idx_executive_memory_source_turn
    ON executive_memory (source_turn_id)
    WHERE source_turn_id IS NOT NULL;
