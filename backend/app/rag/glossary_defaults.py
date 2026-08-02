"""
glossary_defaults.py
────────────────────
Single canonical source of truth for the default Kaggle E-commerce glossary.

These defaults are:
  1. Seeded into `tenant_glossary` for every new tenant via the Clerk webhook.
  2. Used as the fallback by QueryRewriter when a tenant has no custom glossary.
  3. Displayed in the Admin UI Glossary tab for tenants that have not customised.

To add or change the default glossary, edit this file only.
Do NOT add synonyms directly to query_rewriter.py or webhooks.py.
"""

from __future__ import annotations

DEFAULT_METRIC_SYNONYMS: dict[str, list[str]] = {
    "revenue": [
        "revenue",
        "sales",
        "net sales",
        "topline",
        "income",
        "earnings",
        "gross revenue",
        "net revenue",
    ],
    "order_count": [
        "orders",
        "order count",
        "number of orders",
        "purchases",
        "transactions",
        "order volume",
    ],
    "average_order_value": [
        "aov",
        "average order value",
        "avg order",
        "basket size",
        "average ticket",
    ],
    "active_customers": [
        "customers",
        "unique customers",
        "buyers",
        "active customers",
        "active buyers",
    ],
    "units_sold": [
        "units",
        "quantity",
        "volume",
        "units sold",
    ],
    "discount_rate": [
        "discount",
        "discount rate",
        "promotion",
        "markdown",
        "promo",
    ],
}

DEFAULT_TABLE_SYNONYMS: dict[str, list[str]] = {
    "ORDERS": ["orders", "purchases", "transactions", "sales"],
    "ORDER_ITEMS": ["items", "line items", "order details", "products ordered"],
    "CUSTOMERS": ["customers", "buyers", "clients", "users"],
    "PRODUCTS": ["products", "catalog", "inventory", "items", "skus"],
    "SELLERS": ["sellers", "vendors", "suppliers", "merchants"],
    "ORDER_REVIEWS": ["reviews", "ratings", "feedback", "satisfaction"],
    "ORDER_PAYMENTS": ["payments", "payment methods", "billing"],
    "GEOLOCATION": ["location", "region", "geography", "state", "city"],
}

DEFAULT_METRIC_TO_TABLES: dict[str, list[str]] = {
    "revenue": ["ORDERS", "ORDER_ITEMS"],
    "gross_revenue": ["ORDERS", "ORDER_ITEMS"],
    "order_count": ["ORDERS"],
    "average_order_value": ["ORDERS", "ORDER_ITEMS"],
    "active_customers": ["ORDERS", "CUSTOMERS"],
    "units_sold": ["ORDER_ITEMS", "PRODUCTS"],
    "product_revenue": ["ORDER_ITEMS", "PRODUCTS"],
    "discount_rate": ["ORDERS"],
}
