-- Pharma Counterfeit DBMS - security tests (S1-S9)
-- Based on section 6.3 of the project specification.
-- Target: pharma_counterfeit_test (never run these write attempts on the main DB).
--
-- IMPORTANT:
-- MySQL authenticates one user per connection. This file therefore contains
-- separate test sections. Run each section while connected as the account
-- named in its heading. Do NOT execute the entire file under one account.
-- In VS Code/SQLTools, select and execute one section at a time, or copy that
-- section into a terminal connection for the named account.
-- Expected-denial statements are supposed to return MySQL errors. Those errors
-- are the successful result for S1, S2, S4, S5, S8 and S9.

USE pharma_counterfeit_test;

-- ================================================================
-- S1 - readonly: INSERT a shipment must be denied (ERROR 1142)
-- Connect as: readonly
-- ================================================================
INSERT INTO shipment (link_id, ship_time, status)
VALUES (1, NOW(), 'DISPATCHED');

-- ================================================================
-- S2 - detection: reading the simulation answer key must be denied
-- Expected: ERROR 1142 (SELECT command denied)
-- Connect as: detection
-- ================================================================
SELECT * FROM injected_counterfeit LIMIT 1;

-- ================================================================
-- S3 - detection: INSERT into anomaly_flag must be allowed
-- Connect as: detection
-- The automated runner rolls back this transaction after verifying the INSERT.
-- No permanent test flag is left behind.
-- ================================================================
INSERT INTO anomaly_flag (rule_code, severity)
VALUES ('SECURITY_TEST_S3', 'LOW');

SELECT flag_id, rule_code, severity, detected_at
FROM anomaly_flag
WHERE rule_code = 'SECURITY_TEST_S3'
ORDER BY flag_id DESC
LIMIT 1;

-- ================================================================
-- S4 - app: UPDATE trace_event must be denied (ERROR 1142)
-- Connect as: app
-- ================================================================
UPDATE trace_event
SET event_time = event_time
WHERE event_id = 1;

-- ================================================================
-- S5 - app: DELETE shipment must be denied (ERROR 1142)
-- Connect as: app
-- ================================================================
DELETE FROM shipment
WHERE shipment_id = 1;

-- ================================================================
-- S6 - p_5 (M1): v_my_batches must show only M1's batches
-- Expected for the supplied seed: 50 rows; manufacturer_id must be 5.
-- Connect as: p_5
-- ================================================================
SELECT COUNT(*) AS visible_batch_count
FROM v_my_batches;

SELECT COUNT(*) AS rows_not_owned_by_M1
FROM v_my_batches
WHERE manufacturer_id <> 5;

-- ================================================================
-- S7 - p_23 (R1): v_my_stock must show only R1's packs
-- Expected: rows_not_owned_by_R1 = 0; every returned owner is 23.
-- Connect as: p_23
-- ================================================================
SELECT COUNT(*) AS visible_pack_count
FROM v_my_stock;

SELECT COUNT(*) AS rows_not_owned_by_R1
FROM v_my_stock
WHERE current_owner <> 23;

-- ================================================================
-- S8 - ledger: updating trace_event.event_type must be denied
-- Expected: ERROR 1143 (UPDATE command denied for this column).
-- The ledger role may update ledger_synced only.
-- Connect as: ledger
-- ================================================================
UPDATE trace_event
SET event_type = event_type
WHERE event_id = 1;

-- ================================================================
-- S9 - manufacturer (p_5): direct INSERT into batch must be denied
-- Expected: ERROR 1142. Batch creation must use create_batch().
-- Connect as: p_5
-- ================================================================
INSERT INTO batch
    (drug_id, manufacturer_id, batch_no, mfg_date, expiry_date, quantity)
VALUES
    (1, 5, 'SECURITY_TEST_S9', CURRENT_DATE,
     DATE_ADD(CURRENT_DATE, INTERVAL 1 YEAR), 1);

-- End of S1-S9.
