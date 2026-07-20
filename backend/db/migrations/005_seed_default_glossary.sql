-- Migration 005: Seed default glossary for all existing tenants
-- that do not yet have a tenant_glossary row.
--
-- This is idempotent: ON CONFLICT DO NOTHING means re-running
-- this migration has no effect.
--
-- The JSON values here must match DEFAULT_METRIC_SYNONYMS and
-- DEFAULT_TABLE_SYNONYMS in backend/app/rag/glossary_defaults.py.
-- If you update the Python defaults, update this migration too and
-- create a new migration to apply the delta to existing rows.

INSERT INTO tenant_glossary (tenant_id, metric_synonyms, table_synonyms)
SELECT
    id,
    '{
        "revenue": ["revenue","sales","net sales","topline","income","earnings","gross revenue","net revenue"],
        "order_count": ["orders","order count","number of orders","purchases","transactions","order volume"],
        "average_order_value": ["aov","average order value","avg order","basket size","average ticket"],
        "active_customers": ["customers","unique customers","buyers","active customers","active buyers"],
        "units_sold": ["units","quantity","volume","units sold"],
        "discount_rate": ["discount","discount rate","promotion","markdown","promo"]
    }'::jsonb,
    '{
        "ORDERS": ["orders","purchases","transactions","sales"],
        "ORDER_ITEMS": ["items","line items","order details","products ordered"],
        "CUSTOMERS": ["customers","buyers","clients","users"],
        "PRODUCTS": ["products","catalog","inventory","items","skus"],
        "SELLERS": ["sellers","vendors","suppliers","merchants"],
        "ORDER_REVIEWS": ["reviews","ratings","feedback","satisfaction"],
        "ORDER_PAYMENTS": ["payments","payment methods","billing"],
        "GEOLOCATION": ["location","region","geography","state","city"]
    }'::jsonb
FROM tenants
ON CONFLICT (tenant_id) DO NOTHING;
