-- ============================================================
-- VoxQuery Sales Analytics Schema
-- Source: DBSchema_Sqls.docx
-- Dialect: DuckDB-compatible SQL
-- ============================================================

-- Drop tables if they exist (for clean re-runs)
DROP TABLE IF EXISTS ORDER_REVIEWS;
DROP TABLE IF EXISTS ORDER_PAYMENTS;
DROP TABLE IF EXISTS ORDER_ITEMS;
DROP TABLE IF EXISTS ORDERS;
DROP TABLE IF EXISTS SELLERS;
DROP TABLE IF EXISTS PRODUCTS;
DROP TABLE IF EXISTS CUSTOMERS;
DROP TABLE IF EXISTS GEOLOCATION;

-- ─────────────────────────────────────────────────────────────
-- GEOLOCATION
-- Parent table — must be created first
-- ─────────────────────────────────────────────────────────────
CREATE TABLE GEOLOCATION (
    zip_code_prefix  VARCHAR(20)  NOT NULL,
    geolocation_lat  DECIMAL(10,6),
    geolocation_lng  DECIMAL(10,6),
    geolocation_city VARCHAR(100),
    geolocation_state VARCHAR(50),
    PRIMARY KEY (zip_code_prefix)
);

-- ─────────────────────────────────────────────────────────────
-- CUSTOMERS
-- Each customer located by ZIP in GEOLOCATION
-- ─────────────────────────────────────────────────────────────
CREATE TABLE CUSTOMERS (
    customer_id         INTEGER      NOT NULL,
    customer_unique_id  VARCHAR(100),
    customer_name       VARCHAR(150),
    customer_gender     VARCHAR(20),
    customer_age        INTEGER,
    customer_zip_code_prefix VARCHAR(20),
    customer_city       VARCHAR(100),
    customer_state      VARCHAR(50),
    customer_segment    VARCHAR(50),
    PRIMARY KEY (customer_id)
);

-- ─────────────────────────────────────────────────────────────
-- PRODUCTS
-- ─────────────────────────────────────────────────────────────
CREATE TABLE PRODUCTS (
    product_id            INTEGER      NOT NULL,
    product_category_name VARCHAR(100),
    product_name          VARCHAR(200),
    product_brand         VARCHAR(100),
    product_weight_g      INTEGER,
    product_length_cm     DECIMAL(10,2),
    product_height_cm     DECIMAL(10,2),
    product_width_cm      DECIMAL(10,2),
    cost                  DECIMAL(10,2),
    price                 DECIMAL(10,2),
    PRIMARY KEY (product_id)
);

-- ─────────────────────────────────────────────────────────────
-- SELLERS
-- Each seller located by ZIP in GEOLOCATION
-- ─────────────────────────────────────────────────────────────
CREATE TABLE SELLERS (
    seller_id             INTEGER      NOT NULL,
    seller_company_name   VARCHAR(150),
    seller_contact_name   VARCHAR(150),
    seller_contact_gender VARCHAR(20),
    seller_contact_age    INTEGER,
    seller_zip_code_prefix VARCHAR(20),
    seller_city           VARCHAR(100),
    seller_state          VARCHAR(50),
    PRIMARY KEY (seller_id)
);

-- ─────────────────────────────────────────────────────────────
-- ORDERS
-- Order belongs to a customer
-- ─────────────────────────────────────────────────────────────
CREATE TABLE ORDERS (
    order_id                  INTEGER   NOT NULL,
    customer_id               INTEGER,
    order_status              VARCHAR(50),
    order_purchase_timestamp  TIMESTAMP,
    order_approved_at         TIMESTAMP,
    order_delivered_carrier_date TIMESTAMP,
    order_delivered_customer_date TIMESTAMP,
    order_estimated_delivery_date TIMESTAMP,
    PRIMARY KEY (order_id),
    FOREIGN KEY (customer_id) REFERENCES CUSTOMERS(customer_id)
);

-- ─────────────────────────────────────────────────────────────
-- ORDER_ITEMS
-- Item belongs to an order, references product and seller
-- ─────────────────────────────────────────────────────────────
CREATE TABLE ORDER_ITEMS (
    order_id          INTEGER       NOT NULL,
    order_item_id     INTEGER       NOT NULL,
    product_id        INTEGER,
    seller_id         INTEGER,
    shipping_limit_date TIMESTAMP,
    price             DECIMAL(10,2),
    freight_value     DECIMAL(10,2),
    discount_rate     DECIMAL(5,2),
    PRIMARY KEY (order_id, order_item_id),
    FOREIGN KEY (order_id)    REFERENCES ORDERS(order_id),
    FOREIGN KEY (product_id)  REFERENCES PRODUCTS(product_id),
    FOREIGN KEY (seller_id)   REFERENCES SELLERS(seller_id)
);

-- ─────────────────────────────────────────────────────────────
-- ORDER_PAYMENTS
-- Payment tied to an order
-- ─────────────────────────────────────────────────────────────
CREATE TABLE ORDER_PAYMENTS (
    order_id             INTEGER     NOT NULL,
    payment_sequential   INTEGER     NOT NULL,
    payment_type         VARCHAR(50),
    payment_installments INTEGER,
    payment_value        DECIMAL(10,2),
    PRIMARY KEY (order_id, payment_sequential),
    FOREIGN KEY (order_id) REFERENCES ORDERS(order_id)
);

-- ─────────────────────────────────────────────────────────────
-- ORDER_REVIEWS
-- Review written for an order
-- ─────────────────────────────────────────────────────────────
CREATE TABLE ORDER_REVIEWS (
    review_id             INTEGER    NOT NULL,
    order_id              INTEGER,
    review_score          INTEGER,
    review_comment_title  VARCHAR(255),
    review_comment_message TEXT,
    review_creation_date  TIMESTAMP,
    review_answer_timestamp TIMESTAMP,
    PRIMARY KEY (review_id),
    FOREIGN KEY (order_id) REFERENCES ORDERS(order_id)
);

-- ─────────────────────────────────────────────────────────────
-- SEED DATA — Minimal rows for testing and RAG extraction
-- ─────────────────────────────────────────────────────────────

INSERT INTO GEOLOCATION VALUES
    ('10001', 40.748817, -73.985428, 'New York',    'NY'),
    ('90001', 33.973951, -118.248405,'Los Angeles', 'CA'),
    ('60601', 41.885300, -87.618980, 'Chicago',     'IL'),
    ('77001', 29.749907, -95.358421, 'Houston',     'TX'),
    ('85001', 33.448376, -112.074036,'Phoenix',     'AZ');

INSERT INTO CUSTOMERS VALUES
    (1, 'CUST-001', 'Alice Johnson',  'Female', 34, '10001', 'New York',    'NY', 'Premium'),
    (2, 'CUST-002', 'Bob Smith',      'Male',   42, '90001', 'Los Angeles', 'CA', 'Standard'),
    (3, 'CUST-003', 'Carol Davis',    'Female', 28, '60601', 'Chicago',     'IL', 'Premium'),
    (4, 'CUST-004', 'David Wilson',   'Male',   55, '77001', 'Houston',     'TX', 'Standard'),
    (5, 'CUST-005', 'Emma Martinez',  'Female', 31, '85001', 'Phoenix',     'AZ', 'Premium');

INSERT INTO PRODUCTS VALUES
    (1, 'Electronics',  'Widget Pro',      'TechBrand',  500,  20.0, 10.0, 15.0, 150.00, 299.99),
    (2, 'Software',     'Data Suite',      'DataCo',     100,   5.0,  2.0,  5.0,  50.00, 499.99),
    (3, 'Software',     'Cloud Pack',      'CloudInc',   100,   5.0,  2.0,  5.0,  20.00, 199.99),
    (4, 'Hardware',     'Hardware Kit',    'BuildCorp',  800,  25.0, 15.0, 20.0, 100.00, 149.99),
    (5, 'Electronics',  'Smart Sensor',   'TechBrand',  300,  10.0,  5.0,  8.0,  80.00, 189.99);

INSERT INTO SELLERS VALUES
    (1, 'TechBrand Inc',   'John Tech',    'Male',   45, '10001', 'New York',    'NY'),
    (2, 'DataCo LLC',      'Sara Data',    'Female', 38, '90001', 'Los Angeles', 'CA'),
    (3, 'CloudInc Corp',   'Mike Cloud',   'Male',   50, '60601', 'Chicago',     'IL'),
    (4, 'BuildCorp Ltd',   'Lisa Build',   'Female', 42, '77001', 'Houston',     'TX');

INSERT INTO ORDERS VALUES
    (1001, 1, 'delivered', '2024-07-01 10:00:00', '2024-07-01 10:30:00', '2024-07-03 08:00:00', '2024-07-05 14:00:00', '2024-07-06 00:00:00'),
    (1002, 2, 'delivered', '2024-07-15 14:00:00', '2024-07-15 14:15:00', '2024-07-17 09:00:00', '2024-07-19 11:00:00', '2024-07-20 00:00:00'),
    (1003, 3, 'delivered', '2024-08-01 09:00:00', '2024-08-01 09:10:00', '2024-08-03 07:00:00', '2024-08-05 13:00:00', '2024-08-06 00:00:00'),
    (1004, 4, 'delivered', '2024-08-15 16:00:00', '2024-08-15 16:20:00', '2024-08-17 10:00:00', '2024-08-19 15:00:00', '2024-08-20 00:00:00'),
    (1005, 5, 'delivered', '2024-09-01 11:00:00', '2024-09-01 11:05:00', '2024-09-03 08:00:00', '2024-09-05 12:00:00', '2024-09-06 00:00:00'),
    (1006, 1, 'delivered', '2024-09-10 13:00:00', '2024-09-10 13:15:00', '2024-09-12 07:00:00', '2024-09-14 10:00:00', '2024-09-15 00:00:00'),
    (1007, 2, 'cancelled', '2024-09-20 10:00:00', NULL,                  NULL,                  NULL,                  '2024-09-25 00:00:00'),
    (1008, 3, 'delivered', '2024-10-01 09:00:00', '2024-10-01 09:30:00', '2024-10-03 08:00:00', '2024-10-05 11:00:00', '2024-10-06 00:00:00');

INSERT INTO ORDER_ITEMS VALUES
    (1001, 1, 1, 1, '2024-07-08 00:00:00', 299.99, 15.00, 0.05),
    (1001, 2, 3, 3, '2024-07-08 00:00:00', 199.99, 10.00, 0.00),
    (1002, 1, 2, 2, '2024-07-22 00:00:00', 499.99, 20.00, 0.10),
    (1003, 1, 4, 4, '2024-08-08 00:00:00', 149.99,  8.00, 0.00),
    (1003, 2, 5, 1, '2024-08-08 00:00:00', 189.99, 12.00, 0.05),
    (1004, 1, 1, 1, '2024-08-22 00:00:00', 299.99, 15.00, 0.00),
    (1005, 1, 2, 2, '2024-09-08 00:00:00', 499.99, 20.00, 0.10),
    (1005, 2, 3, 3, '2024-09-08 00:00:00', 199.99, 10.00, 0.00),
    (1006, 1, 5, 1, '2024-09-17 00:00:00', 189.99, 12.00, 0.05),
    (1008, 1, 1, 1, '2024-10-08 00:00:00', 299.99, 15.00, 0.00),
    (1008, 2, 4, 4, '2024-10-08 00:00:00', 149.99,  8.00, 0.05);

INSERT INTO ORDER_PAYMENTS VALUES
    (1001, 1, 'credit_card',  3, 524.98),
    (1002, 1, 'credit_card',  1, 449.99),
    (1003, 1, 'debit_card',   1, 347.98),
    (1004, 1, 'credit_card',  2, 314.99),
    (1005, 1, 'credit_card',  6, 699.98),
    (1006, 1, 'boleto',       1, 201.99),
    (1008, 1, 'credit_card',  2, 448.98);

INSERT INTO ORDER_REVIEWS VALUES
    (1, 1001, 5, 'Great product', 'Fast delivery and excellent quality.',   '2024-07-06 10:00:00', '2024-07-07 09:00:00'),
    (2, 1002, 4, 'Good value',    'Happy with the purchase.',               '2024-07-20 12:00:00', '2024-07-21 10:00:00'),
    (3, 1003, 5, 'Perfect',       'Exactly what I needed.',                 '2024-08-06 08:00:00', '2024-08-07 09:00:00'),
    (4, 1004, 3, 'Average',       'Product OK but delivery was slow.',      '2024-08-20 15:00:00', '2024-08-21 10:00:00'),
    (5, 1005, 5, 'Excellent',     'Best purchase this year!',               '2024-09-06 11:00:00', '2024-09-07 10:00:00'),
    (6, 1008, 4, 'Very good',     'Would recommend to others.',             '2024-10-06 09:00:00', '2024-10-07 08:00:00');