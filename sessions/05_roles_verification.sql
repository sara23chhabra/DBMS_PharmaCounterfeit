
USE pharma_counterfeit_db;

-- check detection role privileges
SELECT
    GRANTEE,
    TABLE_NAME,
    PRIVILEGE_TYPE
FROM information_schema.TABLE_PRIVILEGES
WHERE GRANTEE = '''role_detection''@''%'''
  AND TABLE_SCHEMA = 'pharma_counterfeit_db'
ORDER BY TABLE_NAME, PRIVILEGE_TYPE;


-- verify detection cannot read the counterfeit answer key
SELECT
    COUNT(*) AS unexpected_select_grants
FROM information_schema.TABLE_PRIVILEGES
WHERE GRANTEE = '''role_detection''@''%'''
  AND TABLE_SCHEMA = 'pharma_counterfeit_db'
  AND TABLE_NAME = 'injected_counterfeit'
  AND PRIVILEGE_TYPE = 'SELECT';


-- inspect ledger role privileges
SELECT
    GRANTEE,
    TABLE_NAME,
    COLUMN_NAME,
    PRIVILEGE_TYPE
FROM information_schema.COLUMN_PRIVILEGES
WHERE GRANTEE = '''role_ledger''@''%'''
  AND TABLE_SCHEMA = 'pharma_counterfeit_db'
ORDER BY TABLE_NAME, COLUMN_NAME;


-- inspect read-only role view permissions
SELECT
    GRANTEE,
    TABLE_NAME,
    PRIVILEGE_TYPE
FROM information_schema.TABLE_PRIVILEGES
WHERE GRANTEE = '''role_readonly''@''%'''
  AND TABLE_SCHEMA = 'pharma_counterfeit_db'
ORDER BY TABLE_NAME;


-- verify read-only role has no table-level write privileges
SELECT
    TABLE_NAME,
    PRIVILEGE_TYPE
FROM information_schema.TABLE_PRIVILEGES
WHERE GRANTEE = '''role_readonly''@''%'''
  AND TABLE_SCHEMA = 'pharma_counterfeit_db'
  AND PRIVILEGE_TYPE <> 'SELECT';
