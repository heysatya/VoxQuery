# DBschema Review

## Summary

The DBschema branch provides a demo/customer warehouse schema for the VoxQuery MVP. It is not the VoxQuery application metadata schema. The existing VoxQuery app tables (`tenants`, `users`, `conversations`, `turns`, `clarifications`) remain separate from this analytical warehouse schema.

Imported handoff files:

- `DB Info`
- `DBScema_Sqls.docx`
- `DBSchema_Diagram.pdf`
- `voxquery-sampleexecutivequestions.xlsx`

## Source Of Truth

Use `DBSchema_Diagram.pdf` as the current schema source of truth. The Word DDL captures the same intent, but it is not executable as-is.

Known issues in `DBScema_Sqls.docx`:

- OCR/typing errors such as `GEOLOCAT1ON`, `REVIEVVS`, `eignt`, and `witn`.
- Spaces in identifiers such as `order items`, `customer id`, and `zip code prefix`.
- Malformed constraint syntax and comments embedded where SQL clauses should be.
- Missing or mismatched parentheses in several `CREATE TABLE` statements.
- Inconsistent spelling of columns such as `freignt_value`, `payment instalImentslNT`, and `customer zio code prefix`.

## Canonical Tables

The corrected demo warehouse schema contains eight tables:

- `geolocation`
- `customers`
- `products`
- `sellers`
- `orders`
- `order_items`
- `order_payments`
- `order_reviews`

The canonical SQL fixture is `db/demo_warehouse/001_ecommerce_schema.sql`.

## Relationship Map

- `customers.customer_zip_code_prefix` -> `geolocation.zip_code_prefix`
- `sellers.seller_zip_code_prefix` -> `geolocation.zip_code_prefix`
- `orders.customer_id` -> `customers.customer_id`
- `order_items.order_id` -> `orders.order_id`
- `order_items.product_id` -> `products.product_id`
- `order_items.seller_id` -> `sellers.seller_id`
- `order_payments.order_id` -> `orders.order_id`
- `order_reviews.order_id` -> `orders.order_id`

## PRD Alignment

This schema supports the PRD's need for a realistic Snowflake-backed analytical warehouse. It gives the MVP slice concrete business concepts for schema-aware RAG and SQL generation:

- revenue and net revenue
- customer segment
- product category and margin
- seller performance
- geography
- payment behavior
- delivery performance
- customer recency/churn

It does not replace product metadata tables. VoxQuery still needs its application database for sessions, conversations, turns, clarifications, tenant configuration, and audit metadata.

## Effect On Local MVP Slice

The fake local pipeline should use the e-commerce schema instead of generic `finance` and `regions` placeholders. This keeps local behavior aligned with the demo warehouse that other teams are building toward.

For local stubs:

- ambiguous `revenue` should still trigger clarification.
- explicit `net revenue` should map to `SUM(order_items.price * (1 - order_items.discount_rate) + order_items.freight_value)`.
- customer-segment queries should join `customers`, `orders`, and `order_items`.
- geographic queries should join `geolocation`, `customers`, `orders`, and `order_items`.

## Open Questions For DB Team

- Should table and column names be lower-case snake_case in the executable schema, or preserved as upper-case identifiers for Snowflake demos?
- Is `discount_rate` represented as a decimal fraction (`0.10`) or percentage (`10`)?
- Should revenue include `freight_value` by default, or should freight be a separate metric?
- Is `products.cost` per product unit, per order item, or static catalog cost?
- Should `geolocation.zip_code_prefix` be unique enough to serve as a primary key for all cities/states in the synthetic dataset?
