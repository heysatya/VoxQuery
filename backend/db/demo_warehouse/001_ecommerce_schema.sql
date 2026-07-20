-- Canonical demo warehouse schema for the VoxQuery local MVP slice.
-- Source of truth: docs/dbschema/DBSchema_Diagram.pdf.
-- This is separate from VoxQuery application metadata migrations.

CREATE TABLE IF NOT EXISTS geolocation (
  zip_code_prefix VARCHAR(20) PRIMARY KEY,
  geolocation_lat DECIMAL(10, 6),
  geolocation_lng DECIMAL(10, 6),
  geolocation_city VARCHAR(100),
  geolocation_state VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS customers (
  customer_id INT PRIMARY KEY,
  customer_unique_id VARCHAR(100),
  customer_name VARCHAR(150),
  customer_gender VARCHAR(20),
  customer_age INT,
  customer_zip_code_prefix VARCHAR(20),
  customer_city VARCHAR(100),
  customer_state VARCHAR(50),
  customer_segment VARCHAR(50),
  CONSTRAINT fk_customers_geolocation_zip
    FOREIGN KEY (customer_zip_code_prefix)
    REFERENCES geolocation(zip_code_prefix)
    ON DELETE RESTRICT
    ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS products (
  product_id INT PRIMARY KEY,
  product_category_name VARCHAR(100),
  product_name VARCHAR(200),
  product_brand VARCHAR(100),
  product_weight_g INT,
  product_length_cm DECIMAL(10, 2),
  product_height_cm DECIMAL(10, 2),
  product_width_cm DECIMAL(10, 2),
  cost DECIMAL(10, 2),
  price DECIMAL(10, 2)
);

CREATE TABLE IF NOT EXISTS sellers (
  seller_id INT PRIMARY KEY,
  seller_company_name VARCHAR(150),
  seller_contact_name VARCHAR(150),
  seller_contact_gender VARCHAR(20),
  seller_contact_age INT,
  seller_zip_code_prefix VARCHAR(20),
  seller_city VARCHAR(100),
  seller_state VARCHAR(50),
  CONSTRAINT fk_sellers_geolocation_zip
    FOREIGN KEY (seller_zip_code_prefix)
    REFERENCES geolocation(zip_code_prefix)
    ON DELETE RESTRICT
    ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS orders (
  order_id INT PRIMARY KEY,
  customer_id INT,
  order_status VARCHAR(50),
  order_purchase_timestamp TIMESTAMP,
  order_approved_at TIMESTAMP,
  order_delivered_carrier_date TIMESTAMP,
  order_delivered_customer_date TIMESTAMP,
  order_estimated_delivery_date TIMESTAMP,
  CONSTRAINT fk_orders_customers
    FOREIGN KEY (customer_id)
    REFERENCES customers(customer_id)
    ON DELETE RESTRICT
    ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS order_items (
  order_id INT NOT NULL,
  order_item_id INT NOT NULL,
  product_id INT,
  seller_id INT,
  shipping_limit_date TIMESTAMP,
  price DECIMAL(10, 2),
  freight_value DECIMAL(10, 2),
  discount_rate DECIMAL(5, 2),
  CONSTRAINT pk_order_items PRIMARY KEY (order_id, order_item_id),
  CONSTRAINT fk_order_items_orders
    FOREIGN KEY (order_id)
    REFERENCES orders(order_id)
    ON DELETE CASCADE
    ON UPDATE CASCADE,
  CONSTRAINT fk_order_items_products
    FOREIGN KEY (product_id)
    REFERENCES products(product_id)
    ON DELETE RESTRICT
    ON UPDATE CASCADE,
  CONSTRAINT fk_order_items_sellers
    FOREIGN KEY (seller_id)
    REFERENCES sellers(seller_id)
    ON DELETE RESTRICT
    ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS order_payments (
  order_id INT NOT NULL,
  payment_sequential INT NOT NULL,
  payment_type VARCHAR(50),
  payment_installments INT,
  payment_value DECIMAL(10, 2),
  CONSTRAINT pk_order_payments PRIMARY KEY (order_id, payment_sequential),
  CONSTRAINT fk_order_payments_orders
    FOREIGN KEY (order_id)
    REFERENCES orders(order_id)
    ON DELETE CASCADE
    ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS order_reviews (
  review_id INT PRIMARY KEY,
  order_id INT,
  review_score INT,
  review_comment_title VARCHAR(255),
  review_comment_message TEXT,
  review_creation_date TIMESTAMP,
  review_answer_timestamp TIMESTAMP,
  CONSTRAINT fk_order_reviews_orders
    FOREIGN KEY (order_id)
    REFERENCES orders(order_id)
    ON DELETE CASCADE
    ON UPDATE CASCADE
);
