-- AI Smart Export Test Data
-- SQLite 可用完整版
-- 清理现有数据（如果存在）
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS access_logs;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS users;

-- 创建用户表
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT,
    email TEXT,
    age INTEGER,
    score REAL,
    active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO users (id, name, email, age, score, active, created_at) VALUES
(1, 'Alice Smith', 'test"quotes"@example.com', 28, 85.5, 1, CURRENT_TIMESTAMP),
(2, 'Bob Johnson', 'bob@example.com', 35, 72.0, 1, CURRENT_TIMESTAMP),
(3, 'Charlie Brown', 'charlie@example.com', 42, 91.0, 1, CURRENT_TIMESTAMP),
(4, 'Diana Prince', 'diana@example.com', 31, 88.5, 1, CURRENT_TIMESTAMP),
(5, 'Evan King', 'evan@example.com', 29, 77.0, 0, CURRENT_TIMESTAMP),
(6, 'Frank Lloyd', 'frank@example.com', 45, 82.0, 1, CURRENT_TIMESTAMP),
(7, 'Grace Morris', 'grace@example.com', 38, 95.0, 1, CURRENT_TIMESTAMP),
(8, 'Henry Wilson', 'henry@example.com', 52, 78.0, 1, CURRENT_TIMESTAMP),
(9, 'Ivy Chen', 'ivy@example.com', 27, 94.0, 1, CURRENT_TIMESTAMP),
(10, 'Jack Moore', 'jack@example.com', 31, 83.0, 1, CURRENT_TIMESTAMP),
(11, 'No Email User', NULL, 85.0, 1, CURRENT_TIMESTAMP),
(12, 'Partial User', 'partial@test.com', NULL, 70.0, 1, CURRENT_TIMESTAMP),
(13, 'Empty Email User', '', 45.0, 0.0, 1, CURRENT_TIMESTAMP);

-- 创建产品表
CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    name TEXT,
    description TEXT,
    price REAL DEFAULT 0.00,
    quantity INTEGER DEFAULT 0,
    category TEXT,
    manufacturer TEXT,
    sku TEXT UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO products (id, name, description, price, quantity, category, manufacturer, sku, created_at) VALUES
(1, 'Premium Smartphone', 'Product with "quotes" and special chars', 899.99, 25, 'Electronics', 'TechCorp', 'SKU-ELEC-001', CURRENT_TIMESTAMP),
(2, 'Basic Table', 'Simple dining table for modern homes', 349.99, 500, 'Furniture', 'HomeStyle', 'SKU-TABL-002', CURRENT_TIMESTAMP),
(3, 'Garden Tool Kit', 'Professional gardening tool set', 149.99, 150, 'Garden', 'GardenPro', 'SKU-GARD-003', CURRENT_TIMESTAMP),
(4, 'Office Desk Chair', 'Ergonomic office chair with lumbar support', 499.99, 200, 'Office', 'OfficeMax', 'SKU-OFFC-004', CURRENT_TIMESTAMP),
(5, 'Running Shoes', 'Professional running shoes', 129.99, 75, 'Sports', 'SportFit', 'SKU-RUN-005', CURRENT_TIMESTAMP),
(6, 'Tech Guide Book', 'Complete programming guide', 59.99, 200, 'Books', 'BookWorm', 'SKU-BOOK-006', CURRENT_TIMESTAMP),
(7, 'Wireless Speaker', 'Portable wireless speaker with bass boost', 89.99, 100, 'Electronics', 'MusicHub', 'SKU-SPEAK-007', CURRENT_TIMESTAMP),
(8, 'Smart Watch', 'Advanced smartwatch with notifications', 199.99, 30, 'Electronics', 'MusicHub', 'SKU-WATCH-008', CURRENT_TIMESTAMP),
(9, 'CSV Export Tool', 'AI-powered data export tool with CSV/JSON support', 0.00, 1, 'Software', 'TechCorp', 'SKU-CSV-009', CURRENT_TIMESTAMP),
(10, 'JSON Export Tool', 'Data format converter and validator', 0.00, 1, 'Software', 'TechCorp', 'SKU-JSON-010', CURRENT_TIMESTAMP);

-- 创建订单表
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_amount REAL DEFAULT 0.00,
    status TEXT DEFAULT 'pending',
    shipping_address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

INSERT INTO orders (id, user_id, order_date, total_amount, status, shipping_address, created_at) VALUES
(1, 3, '2024-01-15', 299.98, 'completed', '789 Test Street, Apt 3B', CURRENT_TIMESTAMP),
(2, 1, '2024-01-16', 549.99, 'shipped', '123 Market St, Apt 5', CURRENT_TIMESTAMP),
(3, 4, '2024-01-17', 899.99, 'pending', '456 Mall Rd, Apt 12', CURRENT_TIMESTAMP),
(4, 7, '2024-01-18', 159.99, 'completed', '789 Test Street, Apt 3B', CURRENT_TIMESTAMP),
(5, 2, '2024-01-19', 389.99, 'pending', '456 Mall Rd, Apt 12', CURRENT_TIMESTAMP);

-- 【缺失的关键表：订单明细表 order_items】
CREATE TABLE order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER DEFAULT 1,
    unit_price REAL,
    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);
-- 插入测试明细，保证JOIN查询能正常运行
INSERT INTO order_items(order_id,product_id,quantity,unit_price) VALUES
(1, 6, 5, 59.99),
(2, 2, 1, 549.99),
(3, 1, 1, 899.99),
(4, 7, 1, 89.99),
(5, 3, 2, 149.99);

-- 创建访问日志表
CREATE TABLE access_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT,
    resource TEXT,
    ip_address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

INSERT INTO access_logs (user_id, action, resource, ip_address, created_at) VALUES
(1, 'login', 'users', '192.168.1.1', CURRENT_TIMESTAMP),
(2, 'view', 'products', '192.168.1.1', CURRENT_TIMESTAMP),
(3, 'search', 'users', '192.168.1.1', CURRENT_TIMESTAMP),
(4, 'download', 'export', '192.168.1.1', CURRENT_TIMESTAMP),
(3, 'update', 'profile', '192.168.1.1', CURRENT_TIMESTAMP);

-- ========== 修复统计表查询 ==========
SELECT 'Test Data Statistics' as section;
SELECT 'users' as table_name, (SELECT COUNT(*) FROM users) AS row_count UNION ALL
SELECT 'products' as table_name, (SELECT COUNT(*) FROM products) AS row_count UNION ALL
SELECT 'orders' as table_name, (SELECT COUNT(*) FROM orders) AS row_count UNION ALL
SELECT 'access_logs' as table_name, (SELECT COUNT(*) FROM access_logs) AS row_count UNION ALL
SELECT 'order_items' as table_name, (SELECT COUNT(*) FROM order_items) AS row_count
ORDER BY table_name;

-- 下面原有查询场景保留，现在可以正常执行
SELECT 'Users (Table and Rows Count)' as section;
SELECT * FROM users ORDER BY id;

SELECT 'Products (Table and Rows Count)' as section;
SELECT * FROM products ORDER BY id;

SELECT 'Orders (Table and Rows Count)' as section;
SELECT * FROM orders ORDER BY id;

SELECT 'Access Logs (Table and Rows Count)' as section;
SELECT * FROM access_logs ORDER BY created_at;

SELECT 'Order Items (Table and Rows Count)' as section;
SELECT * FROM order_items ORDER BY id;

-- 场景1: 小数据集测试（CSV推荐）
SELECT * FROM users LIMIT 100;

-- 场景2: 大数据集测试（CSV推荐）
SELECT * FROM products;

-- 场景3: 特殊字符测试（JSON推荐）
SELECT * FROM users WHERE email LIKE '%"%' OR name LIKE '%"';

-- 场景4: 复杂数据JOIN测试
SELECT
    u.name,
    u.age,
    u.score,
    p.name as product_name,
    p.price
FROM users u
JOIN orders o ON u.id = o.user_id
JOIN order_items oi ON o.id = oi.order_id
JOIN products p ON oi.product_id = p.id
WHERE o.status = 'completed'
ORDER BY u.id;

-- 场景5: 空值处理测试
SELECT
    u.name,
    u.email,
    u.score,
    u.active,
    CASE
        WHEN u.email IS NULL OR u.email = '' THEN 'NO_EMAIL'
        WHEN u.email LIKE '%@%' THEN 'VALID_EMAIL'
        ELSE 'INVALID_EMAIL'
    END as email_status
FROM users
ORDER BY u.id;

-- 场景6: 数据类型分析
SELECT
    COUNT(*) as total_records,
    SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) as active_users,
    AVG(age) as average_age,
    AVG(score) as average_score,
    COUNT(*) - SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) as inactive_users
FROM users;

-- 场景7: 价格分析
SELECT
    category,
    COUNT(*) as product_count,
    MIN(price) as min_price,
    MAX(price) as max_price,
    AVG(price) as avg_price,
    SUM(quantity) as total_quantity
FROM products
GROUP BY category
ORDER BY avg_price DESC;

-- 场景8: 文本内容长度测试
SELECT
    p.name as product_name,
    p.description as description,
    LENGTH(p.description) as description_length,
    CASE
        WHEN LENGTH(p.description) > 50 THEN 'LONG_DESCRIPTION'
        WHEN LENGTH(p.description) > 20 THEN 'MEDIUM_DESCRIPTION'
        ELSE 'SHORT_DESCRIPTION'
    END as description_category
FROM products
WHERE id > 5
ORDER BY description_length DESC;

-- 场景9: 导出友好测试数据
SELECT
    u.name,
    u.age,
    u.score,
    u.active,
    p.name as product_name,
    o.total_amount as order_amount,
    o.status as order_status,
    COUNT(oi.id) as item_count
FROM users u
JOIN orders o ON u.id = o.user_id
JOIN order_items oi ON o.id = oi.order_id
JOIN products p ON oi.product_id = p.id
GROUP BY u.id, o.id, p.id
ORDER BY u.id, o.id DESC
LIMIT 20;

-- 场景10: 统计信息
SELECT
    COUNT(*) as total_users,
    SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) as active_users,
    COUNT(*) - SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) as inactive_users,
    AVG(age) as avg_age,
    AVG(score) as avg_score,
    MIN(score) as min_score,
    MAX(score) as max_score,
    COUNT(CASE WHEN email IS NULL THEN 1 ELSE 0 END) as no_email_users,
    COUNT(CASE WHEN email LIKE '%@%' THEN 1 ELSE 0 END) as valid_email_users
FROM users;
