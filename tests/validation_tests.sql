-- =====================================================================
-- Pharma Supply Chain DBMS Project
-- validation_tests.sql : validation demo for the teacher document (Person A)
--
-- Needs: 01_schema.sql, the seed data, 02_triggers.sql, 03_procedures.sql.
--
-- Most tests are SUPPOSED to fail; the error message is the result.
-- Run from a terminal so the script continues after each error and the
-- output lands in one file:
--
--   mysql -u root -p --force --verbose --unbuffered --table pharma_counterfeit_db < tests/validation_tests.sql > validation_output.txt 2>&1
--
-- (In Workbench a script stops at the first error; there, run one test
--  at a time instead.)
--
-- The last section deletes everything the tests created, so the database
-- ends as it started. Do not run the ledger writer in the middle.
--
-- IDs from the seed: S3 = 3, M1 = 5, M2 = 6, D1 = 8, R1 = 23, CONSUMER = 103.
-- =====================================================================

USE pharma_counterfeit_db;

SET @seed_loading = NULL;
SET @tamper_demo  = NULL;

-- Remember where the tables end, for the cleanup at the bottom.
SELECT COALESCE(MAX(flag_id), 0)     INTO @f0  FROM anomaly_flag;
SELECT COALESCE(MAX(event_id), 0)    INTO @e0  FROM trace_event;
SELECT COALESCE(MAX(shipment_id), 0) INTO @sh0 FROM shipment;
SELECT COALESCE(MAX(batch_id), 0)    INTO @b0  FROM batch;
SELECT COALESCE(MAX(history_id), 0)  INTO @h0  FROM license_history;

-- A distributor that M1 supplies, and a retailer that distributor supplies.
SELECT to_participant INTO @d FROM link WHERE from_participant = 5  ORDER BY link_id LIMIT 1;
SELECT to_participant INTO @r FROM link WHERE from_participant = @d ORDER BY link_id LIMIT 1;
-- Two lots delivered to M1, and one delivered to M2.
SELECT GROUP_CONCAT(lot_id) INTO @lots
FROM (SELECT lot_id FROM material_lot WHERE manufacturer_id = 5 ORDER BY lot_id LIMIT 2) x;
SELECT lot_id INTO @other_lot FROM material_lot WHERE manufacturer_id = 6 ORDER BY lot_id LIMIT 1;
-- Batch numbers unique to this run.
SET @bn = CONCAT('VT-', DATE_FORMAT(NOW(), '%d%H%i%s'));

SELECT @d AS distributor, @r AS retailer, @lots AS m1_lots, @other_lot AS m2_lot, @bn AS batch_no;

-- =====================================================================
-- PART V : constraints (CHECK, FOREIGN KEY, UNIQUE) from 01_schema.sql
-- =====================================================================

SELECT 'V1: drug with a 5-digit GTIN' AS test;
INSERT INTO drug (generic_name, brand_name, strength, dosage_form, units_per_pack, gtin, pack_price)
VALUES ('Testdrug', 'Testbrand', '1 mg', 'TABLET', 10, '12345', 10.00);

SELECT 'V2: drug with pack price 0' AS test;
INSERT INTO drug (generic_name, brand_name, strength, dosage_form, units_per_pack, gtin, pack_price)
VALUES ('Testdrug', 'Testbrand', '1 mg', 'TABLET', 10, '8900000000001', 0);

SELECT 'V3: batch that expires before it is made' AS test;
INSERT INTO batch (drug_id, manufacturer_id, batch_no, mfg_date, expiry_date, quantity)
VALUES (1, 5, CONCAT(@bn, '-V3'), '2026-10-01', '2026-01-01', 10);

SELECT 'V4: license that ends before it is issued' AS test;
INSERT INTO participant (name, participant_type, license_no, license_status,
                         license_issue_date, license_valid_till, city, state)
VALUES ('Test Pharmacy', 'RETAILER', 'XX-RET-2026-00001', 'ACTIVE',
        '2026-01-01', '2025-01-01', 'Pune', 'Maharashtra');

SELECT 'V5: link from M1 to itself (trigger 3 switched off to show the CHECK behind it)' AS test;
SET @seed_loading = 1;
INSERT INTO link (from_participant, to_participant) VALUES (5, 5);
SET @seed_loading = NULL;

SELECT 'V6: shipment marked RECEIVED with no receive time' AS test;
INSERT INTO shipment (link_id, ship_time, receive_time, status)
VALUES (1, '2026-10-01 10:00:00', NULL, 'RECEIVED');

SELECT 'V7: shipment received before it was shipped' AS test;
INSERT INTO shipment (link_id, ship_time, receive_time, status)
VALUES (1, '2026-10-01 10:00:00', '2026-09-30 10:00:00', 'RECEIVED');

SELECT 'V8: MANUFACTURED event that has a shipment' AS test;
INSERT INTO trace_event (serial_no, event_type, shipment_id, event_time)
VALUES ('VTEST0000001', 'MANUFACTURED', 1, NOW());

SELECT 'V9: license history row where nothing changed' AS test;
INSERT INTO license_history (participant_id, old_status, new_status, changed_at)
VALUES (5, 'ACTIVE', 'ACTIVE', NOW());

SELECT 'V10: risk score of 1.5' AS test;
INSERT INTO link_risk_score (link_id, risk_score, model_version) VALUES (1, 1.5, 'test');

SELECT 'V11: material lot of 0 kg' AS test;
INSERT INTO material_lot (lot_no, material_name, quantity_sent_kg, quantity_received_kg,
                          supplier_id, manufacturer_id, received_date, coa_verified)
VALUES (CONCAT(@bn, '-V11'), 'Maize starch', 0, 100, 3, 5, '2026-10-01', TRUE);

SELECT 'V12: shipment item for a serial that is not a pack' AS test;
INSERT INTO shipment_item (shipment_id, serial_no, received) VALUES (1, 'NOSUCHSERIAL', FALSE);

SELECT 'V13: batch for a drug that does not exist' AS test;
INSERT INTO batch (drug_id, manufacturer_id, batch_no, mfg_date, expiry_date, quantity)
VALUES (999, 5, CONCAT(@bn, '-V13'), '2026-10-01', '2028-10-01', 10);

SELECT 'V14: second drug with an existing GTIN' AS test;
INSERT INTO drug (generic_name, brand_name, strength, dosage_form, units_per_pack, gtin, pack_price)
SELECT 'Copy', 'Copy', '1 mg', 'TABLET', 10, gtin, 10.00 FROM drug WHERE drug_id = 1;

SELECT 'V15: second batch with the same manufacturer and batch number' AS test;
INSERT INTO batch (drug_id, manufacturer_id, batch_no, mfg_date, expiry_date, quantity)
SELECT drug_id, manufacturer_id, batch_no, mfg_date, expiry_date, quantity
FROM batch WHERE batch_id = 1;

-- =====================================================================
-- PART T : business rules (triggers and stored procedures)
-- =====================================================================

SELECT 'T1: material lot whose supplier is retailer R1 (23)' AS test;
INSERT INTO material_lot (lot_no, material_name, quantity_sent_kg, quantity_received_kg,
                          supplier_id, manufacturer_id, received_date, coa_verified)
VALUES (CONCAT(@bn, '-T1'), 'Maize starch', 100, 100, 23, 5, '2026-10-01', TRUE);

SELECT 'T2: batch whose manufacturer is distributor D1 (8)' AS test;
INSERT INTO batch (drug_id, manufacturer_id, batch_no, mfg_date, expiry_date, quantity)
VALUES (1, 8, CONCAT(@bn, '-T2'), '2026-10-01', '2028-10-01', 10);

SELECT 'T3: link from distributor D1 (8) back to manufacturer M1 (5)' AS test;
INSERT INTO link (from_participant, to_participant) VALUES (8, 5);

SELECT 'T8: create_batch at M1 using a lot delivered to M2' AS test;
CALL create_batch(1, 5, CONCAT(@bn, '-T8'), CURDATE(), DATE_ADD(CURDATE(), INTERVAL 2 YEAR),
                  6, @other_lot, @x);

SELECT 'T6: create_batch with a lot ID that does not exist. The batch row is inserted first, then the lot link fails, so the whole transaction is rolled back' AS test;
CALL create_batch(1, 5, CONCAT(@bn, '-RB'), CURDATE(), DATE_ADD(CURDATE(), INTERVAL 2 YEAR),
                  6, '99999999', @x);
SELECT COUNT(*) AS batches_saved_by_T6 FROM batch WHERE batch_no = CONCAT(@bn, '-RB');

SELECT 'Setup: a valid batch of 6 packs at M1 (stays PENDING)' AS test;
CALL create_batch(1, 5, @bn, CURDATE(), DATE_ADD(CURDATE(), INTERVAL 2 YEAR), 6, @lots, @b);
SELECT batch_id, batch_no, quantity, qc_status, batch_hash FROM batch WHERE batch_id = @b;
SELECT * FROM batch_material WHERE batch_id = @b;

SELECT 'T7: generate packs for a batch that is still PENDING' AS test;
CALL generate_packs(@b);

SELECT 'Setup: approve the batch, generate its packs' AS test;
CALL approve_batch(@b);
CALL generate_packs(@b);
SELECT p.serial_no, p.current_owner, p.status, e.event_type, e.event_hash
FROM pack p JOIN trace_event e ON e.serial_no = p.serial_no
WHERE p.batch_id = @b ORDER BY p.serial_no;

SELECT serial_no INTO @s1 FROM pack WHERE batch_id = @b ORDER BY serial_no LIMIT 1 OFFSET 0;
SELECT serial_no INTO @s2 FROM pack WHERE batch_id = @b ORDER BY serial_no LIMIT 1 OFFSET 1;
SELECT serial_no INTO @s3 FROM pack WHERE batch_id = @b ORDER BY serial_no LIMIT 1 OFFSET 2;
SELECT serial_no INTO @s4 FROM pack WHERE batch_id = @b ORDER BY serial_no LIMIT 1 OFFSET 3;
SELECT serial_no INTO @s5 FROM pack WHERE batch_id = @b ORDER BY serial_no LIMIT 1 OFFSET 4;

SELECT 'T12: dispatch two packs M1 -> distributor, then receive them; pack state follows (trigger 5)' AS test;
CALL dispatch_shipment(5, @d, CONCAT(@s1, ',', @s2), @sh1);
SELECT serial_no, current_owner, status FROM pack WHERE serial_no IN (@s1, @s2);
CALL receive_shipment(@sh1, CONCAT(@s1, ',', @s2));
SELECT serial_no, current_owner, status FROM pack WHERE serial_no IN (@s1, @s2);

SELECT 'T9: dispatch two packs; one arrives, one is missing, and one unknown serial turns up' AS test;
CALL dispatch_shipment(5, @d, CONCAT(@s3, ',', @s4), @sh2);
CALL receive_shipment(@sh2, CONCAT(@s3, ',VTFAKE000001'));
SELECT rule_code, serial_no, shipment_id, link_id, event_id, severity
FROM anomaly_flag WHERE flag_id > @f0 ORDER BY flag_id;

SELECT 'T5: the distributor dispatches a pack that is still at the factory' AS test;
CALL dispatch_shipment(@d, @r, @s5, @x);

SELECT 'T4: suspend the distributor (history row appears by itself), then it tries to dispatch' AS test;
UPDATE participant SET license_status = 'SUSPENDED' WHERE participant_id = @d;
SELECT * FROM license_history WHERE history_id > @h0;
CALL dispatch_shipment(@d, @r, @s2, @x);
UPDATE participant SET license_status = 'ACTIVE' WHERE participant_id = @d;

SELECT 'T10: sell a pack, then try to sell the same serial again' AS test;
CALL dispatch_shipment(@d, @r, CONCAT(@s1, ',', @s2), @sh3);
CALL receive_shipment(@sh3, CONCAT(@s1, ',', @s2));
CALL sell_pack(@r, @s1, @res);
SELECT @res AS first_sale;
CALL sell_pack(@r, @s1, @res);
SELECT @res AS second_sale;
SELECT rule_code, serial_no, link_id, event_id, severity
FROM anomaly_flag WHERE flag_id > @f0 AND rule_code = 'SOLD_TWICE';

SELECT 'T11: sell a pack from an expired batch' AS test;
CALL create_batch(1, 5, CONCAT(@bn, '-EXP'), '2024-01-01', '2025-01-01', 1, @lots, @bx);
CALL approve_batch(@bx);
CALL generate_packs(@bx);
SELECT serial_no INTO @e1 FROM pack WHERE batch_id = @bx;
CALL dispatch_shipment(5, @d, @e1, @sh4);
CALL receive_shipment(@sh4, @e1);
CALL dispatch_shipment(@d, @r, @e1, @sh5);
CALL receive_shipment(@sh5, @e1);
CALL sell_pack(@r, @e1, @res);

SELECT 'T13: recall the batch (recursive CTE lists everyone its packs reached)' AS test;
CALL recall_batch(@b);
SELECT serial_no, current_owner, status FROM pack WHERE batch_id = @b ORDER BY serial_no;
SELECT 'T13b: selling a recalled pack' AS test;
CALL sell_pack(@r, @s2, @res);

SELECT 'Check: every event written by the tests has a hash' AS test;
SELECT COUNT(*) AS new_events, SUM(event_hash IS NOT NULL) AS with_hash
FROM trace_event WHERE event_id > @e0;

-- =====================================================================
-- CLEANUP : remove everything the tests created
-- (deleting events needs the tamper switch, because trace_event is append-only)
-- =====================================================================
SELECT 'Cleanup' AS test;
SET @tamper_demo = 1;
DELETE FROM anomaly_flag    WHERE flag_id     > @f0;
DELETE FROM trace_event     WHERE event_id    > @e0;
DELETE FROM shipment_item   WHERE shipment_id > @sh0;
DELETE FROM shipment        WHERE shipment_id > @sh0;
DELETE FROM pack            WHERE batch_id    > @b0;
DELETE FROM batch_material  WHERE batch_id    > @b0;
DELETE FROM batch           WHERE batch_id    > @b0;
DELETE FROM license_history WHERE history_id  > @h0;
SET @tamper_demo = NULL;

SELECT (SELECT COUNT(*) FROM batch)       AS batches,
       (SELECT COUNT(*) FROM pack)        AS packs,
       (SELECT COUNT(*) FROM shipment)    AS shipments,
       (SELECT COUNT(*) FROM trace_event) AS events,
       (SELECT license_status FROM participant WHERE participant_id = @d) AS distributor_license;
-- Expected after cleanup on the seed: 150, 48468, 37977, 271250, ACTIVE
