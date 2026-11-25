
USE pharma_counterfeit_db;

-- 1. show the development user's privileges
SHOW GRANTS FOR 'pharma_dev'@'localhost';

-- 2. show all project role privileges
SHOW GRANTS FOR 'role_admin'@'%';
SHOW GRANTS FOR 'role_app'@'%';
SHOW GRANTS FOR 'role_manufacturer'@'%';
SHOW GRANTS FOR 'role_retailer'@'%';
SHOW GRANTS FOR 'role_detection'@'%';
SHOW GRANTS FOR 'role_ledger'@'%';
SHOW GRANTS FOR 'role_readonly'@'%';

-- 3. inspect detection role table privileges
SELECT
    GRANTEE,
    TABLE_NAME,
    PRIVILEGE_TYPE
FROM information_schema.TABLE_PRIVILEGES
WHERE GRANTEE = '''role_detection''@''%'''
  AND TABLE_SCHEMA = 'pharma_counterfeit_db'
ORDER BY TABLE_NAME, PRIVILEGE_TYPE;

-- 4. verify detection cannot read the counterfeit answer key
SELECT
    COUNT(*) AS unexpected_select_grants
FROM information_schema.TABLE_PRIVILEGES
WHERE GRANTEE = '''role_detection''@''%'''
  AND TABLE_SCHEMA = 'pharma_counterfeit_db'
  AND TABLE_NAME = 'injected_counterfeit'
  AND PRIVILEGE_TYPE = 'SELECT';

-- 5. inspect ledger role column privileges
SELECT
    GRANTEE,
    TABLE_NAME,
    COLUMN_NAME,
    PRIVILEGE_TYPE
FROM information_schema.COLUMN_PRIVILEGES
WHERE GRANTEE = '''role_ledger''@''%'''
  AND TABLE_SCHEMA = 'pharma_counterfeit_db'
ORDER BY TABLE_NAME, COLUMN_NAME;

-- 6. inspect read-only role view permissions
SELECT
    GRANTEE,
    TABLE_NAME,
    PRIVILEGE_TYPE
FROM information_schema.TABLE_PRIVILEGES
WHERE GRANTEE = '''role_readonly''@''%'''
  AND TABLE_SCHEMA = 'pharma_counterfeit_db'
ORDER BY TABLE_NAME;

-- 7. verify read-only role has no table-level write privileges
SELECT
    TABLE_NAME,
    PRIVILEGE_TYPE
FROM information_schema.TABLE_PRIVILEGES
WHERE GRANTEE = '''role_readonly''@''%'''
  AND TABLE_SCHEMA = 'pharma_counterfeit_db'
  AND PRIVILEGE_TYPE <> 'SELECT';
