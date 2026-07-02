from pathlib import Path


def test_demo_warehouse_schema_contains_expected_tables_and_relationships():
    root = Path(__file__).resolve().parents[2]
    sql = (root / "db" / "demo_warehouse" / "001_ecommerce_schema.sql").read_text()

    for table in [
        "geolocation",
        "customers",
        "products",
        "sellers",
        "orders",
        "order_items",
        "order_payments",
        "order_reviews",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql

    assert "FOREIGN KEY (customer_id)" in sql
    assert "REFERENCES customers(customer_id)" in sql
    assert "FOREIGN KEY (product_id)" in sql
    assert "REFERENCES products(product_id)" in sql
