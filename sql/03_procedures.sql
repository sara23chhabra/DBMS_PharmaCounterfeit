-- =====================================================================
-- Pharma Supply Chain DBMS Project
-- 03_procedures.sql : stored procedures (Person A)
--
-- Run after 02_triggers.sql. Safe to run again.
--
--   fill_event_hashes   helper: computes event_hash for new events
--   create_batch        batch + batch_material + batch_hash
--   approve_batch       QC: PENDING -> APPROVED
--   generate_packs      packs + MANUFACTURED events
--   dispatch_shipment   shipment + items + DISPATCHED events
--   receive_shipment    compares scanned serials with the dispatch list
--   sell_pack           one-pack shipment to CONSUMER + SOLD event
--   recall_batch        recursive CTE + RECALLED events
--
-- Pattern used by every procedure
--   1. Read and check first. A broken rule raises
--        SIGNAL SQLSTATE '45000' with 'CODE: plain sentence'.
--   2. START TRANSACTION ... COMMIT around all writes.
--   3. EXIT HANDLER FOR SQLEXCEPTION: on any error, ROLLBACK and pass the
--      same error on (RESIGNAL). So a procedure saves everything or nothing.
--
-- Lists (serials, lot IDs) are passed as one comma-separated string, e.g.
-- 'ABC123,DEF456'. JSON_TABLE turns the string into rows.
--
-- Why temporary tables: the pack-state trigger updates `pack` whenever an
-- event is inserted. MySQL refuses that if the INSERT itself is reading
-- `pack` (error 1442). So serials are first copied into a temporary table
-- and events are inserted from there.
-- =====================================================================

USE pharma_counterfeit_db;

DELIMITER $$

-- ---------------------------------------------------------------------
-- Helper: fill event_hash for every event newer than p_after_event_id
-- that has no hash yet. Callers note MAX(event_id) before inserting and
-- pass it here, so only their own new rows are touched.
--
-- event_hash = SHA-256 of
--   event_id|serial_no|event_type|from|to|shipment_id|event_time
--   shipment events : from/to = the shipment's link
--   MANUFACTURED    : from = to = the batch's manufacturer, shipment_id empty
--   RECALLED        : from = to = the pack's owner (unchanged by a recall)
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS fill_event_hashes $$
CREATE PROCEDURE fill_event_hashes(IN p_after_event_id BIGINT UNSIGNED)
BEGIN
  UPDATE trace_event e
  JOIN shipment s ON s.shipment_id = e.shipment_id
  JOIN link l     ON l.link_id = s.link_id
  SET e.event_hash = SHA2(CONCAT(
        e.event_id, '|', e.serial_no, '|', e.event_type, '|',
        l.from_participant, '|', l.to_participant, '|', e.shipment_id, '|',
        DATE_FORMAT(e.event_time, '%Y-%m-%d %H:%i:%s')), 256)
  WHERE e.event_id > p_after_event_id
    AND e.event_hash IS NULL;

  UPDATE trace_event e
  JOIN pack p  ON p.serial_no = e.serial_no
  JOIN batch b ON b.batch_id = p.batch_id
  SET e.event_hash = SHA2(CONCAT(
        e.event_id, '|', e.serial_no, '|', e.event_type, '|',
        b.manufacturer_id, '|', b.manufacturer_id, '||',
        DATE_FORMAT(e.event_time, '%Y-%m-%d %H:%i:%s')), 256)
  WHERE e.event_id > p_after_event_id
    AND e.event_type = 'MANUFACTURED'
    AND e.event_hash IS NULL;

  UPDATE trace_event e
  JOIN pack p ON p.serial_no = e.serial_no
  SET e.event_hash = SHA2(CONCAT(
        e.event_id, '|', e.serial_no, '|', e.event_type, '|',
        p.current_owner, '|', p.current_owner, '||',
        DATE_FORMAT(e.event_time, '%Y-%m-%d %H:%i:%s')), 256)
  WHERE e.event_id > p_after_event_id
    AND e.event_type = 'RECALLED'
    AND e.event_hash IS NULL;
END $$

-- ---------------------------------------------------------------------
-- create_batch
--   Registers a production run (qc_status PENDING) and the lots it used.
--   Refuses: NO_LOTS, LOT_NOT_AT_FACTORY (a lot delivered to another factory).
--   A lot ID that does not exist is caught by the foreign key on
--   batch_material; the batch row inserted just before is rolled back.
--
--   batch_hash = SHA-256 of
--     batch_id|drug_id|manufacturer_id|batch_no|mfg_date|expiry_date|quantity|lot IDs
--   (lot IDs sorted ascending, joined with ','; qc_status is not included)
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS create_batch $$
CREATE PROCEDURE create_batch(
  IN  p_drug_id          INT UNSIGNED,
  IN  p_manufacturer_id  INT UNSIGNED,
  IN  p_batch_no         VARCHAR(30),
  IN  p_mfg_date         DATE,
  IN  p_expiry_date      DATE,
  IN  p_quantity         INT UNSIGNED,
  IN  p_lot_ids          VARCHAR(500),
  OUT p_batch_id         INT UNSIGNED)
BEGIN
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  DROP TEMPORARY TABLE IF EXISTS tmp_lots;
  CREATE TEMPORARY TABLE tmp_lots (lot_id INT UNSIGNED PRIMARY KEY);
  INSERT INTO tmp_lots (lot_id)
  SELECT DISTINCT CAST(j.s AS UNSIGNED)
  FROM JSON_TABLE(CONCAT('["', REPLACE(REPLACE(p_lot_ids, ' ', ''), ',', '","'), '"]'),
                  '$[*]' COLUMNS (s VARCHAR(20) PATH '$')) AS j
  WHERE j.s IS NOT NULL AND j.s <> '';

  IF (SELECT COUNT(*) FROM tmp_lots) = 0 THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'NO_LOTS: A batch must use at least one material lot';
  END IF;

  IF EXISTS (SELECT 1
             FROM tmp_lots t
             JOIN material_lot m ON m.lot_id = t.lot_id
             WHERE m.manufacturer_id <> p_manufacturer_id) THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'LOT_NOT_AT_FACTORY: A lot in the list was delivered to another manufacturer';
  END IF;

  START TRANSACTION;

  INSERT INTO batch (drug_id, manufacturer_id, batch_no, mfg_date, expiry_date, quantity, qc_status)
  VALUES (p_drug_id, p_manufacturer_id, p_batch_no, p_mfg_date, p_expiry_date, p_quantity, 'PENDING');
  SET p_batch_id = LAST_INSERT_ID();

  INSERT INTO batch_material (batch_id, lot_id)
  SELECT p_batch_id, lot_id FROM tmp_lots;

  UPDATE batch
  SET batch_hash = SHA2(CONCAT(
        batch_id, '|', drug_id, '|', manufacturer_id, '|', batch_no, '|',
        DATE_FORMAT(mfg_date, '%Y-%m-%d'), '|', DATE_FORMAT(expiry_date, '%Y-%m-%d'), '|',
        quantity, '|',
        (SELECT GROUP_CONCAT(bm.lot_id ORDER BY bm.lot_id SEPARATOR ',')
         FROM batch_material bm WHERE bm.batch_id = p_batch_id)), 256)
  WHERE batch_id = p_batch_id;

  COMMIT;
END $$

-- ---------------------------------------------------------------------
-- approve_batch : quality control passes the batch (PENDING -> APPROVED)
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS approve_batch $$
CREATE PROCEDURE approve_batch(IN p_batch_id INT UNSIGNED)
BEGIN
  UPDATE batch SET qc_status = 'APPROVED'
  WHERE batch_id = p_batch_id AND qc_status = 'PENDING';

  IF ROW_COUNT() = 0 THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'BATCH_NOT_PENDING: Only a PENDING batch can be approved';
  END IF;
END $$

-- ---------------------------------------------------------------------
-- generate_packs
--   Creates batch.quantity packs for an APPROVED batch. Each gets a random
--   12-character serial (A-Z without I and O, digits 2-9: 32 symbols, no
--   look-alikes) and one MANUFACTURED event with its hash.
--   Refuses: BATCH_NOT_FOUND, BATCH_NOT_APPROVED, PACKS_ALREADY_GENERATED.
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS generate_packs $$
CREATE PROCEDURE generate_packs(IN p_batch_id INT UNSIGNED)
BEGIN
  DECLARE v_quantity      INT UNSIGNED;
  DECLARE v_status        VARCHAR(10);
  DECLARE v_manufacturer  INT UNSIGNED;
  DECLARE v_alphabet      CHAR(32) DEFAULT 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  DECLARE v_serial        VARCHAR(20);
  DECLARE v_made          INT UNSIGNED DEFAULT 0;
  DECLARE v_i             INT;
  DECLARE v_before        BIGINT UNSIGNED;
  DECLARE v_now           DATETIME DEFAULT NOW();

  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  SELECT quantity, qc_status, manufacturer_id
    INTO v_quantity, v_status, v_manufacturer
  FROM batch WHERE batch_id = p_batch_id;

  IF v_quantity IS NULL THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'BATCH_NOT_FOUND: No batch with this ID';
  END IF;
  IF v_status <> 'APPROVED' THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'BATCH_NOT_APPROVED: Packs can be generated only for an APPROVED batch';
  END IF;
  IF EXISTS (SELECT 1 FROM pack WHERE batch_id = p_batch_id) THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'PACKS_ALREADY_GENERATED: This batch already has its packs';
  END IF;

  DROP TEMPORARY TABLE IF EXISTS tmp_new_serials;
  CREATE TEMPORARY TABLE tmp_new_serials (serial_no VARCHAR(20) PRIMARY KEY);

  WHILE v_made < v_quantity DO
    SET v_serial = '';
    SET v_i = 0;
    WHILE v_i < 12 DO
      SET v_serial = CONCAT(v_serial, SUBSTRING(v_alphabet, FLOOR(1 + RAND() * 32), 1));
      SET v_i = v_i + 1;
    END WHILE;
    IF NOT EXISTS (SELECT 1 FROM pack WHERE serial_no = v_serial) THEN
      INSERT IGNORE INTO tmp_new_serials (serial_no) VALUES (v_serial);
      SET v_made = v_made + ROW_COUNT();     -- 0 if the serial repeated
    END IF;
  END WHILE;

  START TRANSACTION;

  INSERT INTO pack (serial_no, batch_id, current_owner, status)
  SELECT serial_no, p_batch_id, v_manufacturer, 'IN_STOCK' FROM tmp_new_serials;

  SELECT COALESCE(MAX(event_id), 0) INTO v_before FROM trace_event;

  INSERT INTO trace_event (serial_no, event_type, shipment_id, event_time)
  SELECT serial_no, 'MANUFACTURED', NULL, v_now FROM tmp_new_serials;

  CALL fill_event_hashes(v_before);

  COMMIT;
END $$

-- ---------------------------------------------------------------------
-- dispatch_shipment
--   The sender hands packs to a carrier for the receiver.
--   Refuses: NO_LINK, USE_SELL_PACK, NO_SERIALS, NOT_OWNER, NOT_IN_STOCK,
--   and LICENSE_NOT_ACTIVE (raised by trigger 6 when the shipment row is
--   inserted). One bad serial refuses the whole shipment.
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS dispatch_shipment $$
CREATE PROCEDURE dispatch_shipment(
  IN  p_from_id      INT UNSIGNED,
  IN  p_to_id        INT UNSIGNED,
  IN  p_serials      TEXT,
  OUT p_shipment_id  INT UNSIGNED)
BEGIN
  DECLARE v_link    INT UNSIGNED;
  DECLARE v_before  BIGINT UNSIGNED;
  DECLARE v_now     DATETIME DEFAULT NOW();

  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  SET v_link = (SELECT link_id FROM link
                WHERE from_participant = p_from_id AND to_participant = p_to_id);
  IF v_link IS NULL THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'NO_LINK: These two participants have no trading link';
  END IF;
  IF (SELECT participant_type FROM participant WHERE participant_id = p_to_id) = 'CONSUMER' THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'USE_SELL_PACK: Sales to a consumer go through sell_pack';
  END IF;

  DROP TEMPORARY TABLE IF EXISTS tmp_serials;
  CREATE TEMPORARY TABLE tmp_serials (serial_no VARCHAR(20) PRIMARY KEY);
  INSERT INTO tmp_serials (serial_no)
  SELECT DISTINCT j.s
  FROM JSON_TABLE(CONCAT('["', REPLACE(REPLACE(p_serials, ' ', ''), ',', '","'), '"]'),
                  '$[*]' COLUMNS (s VARCHAR(20) PATH '$')) AS j
  WHERE j.s IS NOT NULL AND j.s <> '';

  IF (SELECT COUNT(*) FROM tmp_serials) = 0 THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'NO_SERIALS: The serial list is empty';
  END IF;

  IF EXISTS (SELECT 1
             FROM tmp_serials t
             LEFT JOIN pack p ON p.serial_no = t.serial_no
             WHERE p.serial_no IS NULL OR p.current_owner <> p_from_id) THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'NOT_OWNER: The sender does not own every pack in the list';
  END IF;

  IF EXISTS (SELECT 1
             FROM tmp_serials t
             JOIN pack p ON p.serial_no = t.serial_no
             WHERE p.status <> 'IN_STOCK') THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'NOT_IN_STOCK: Every pack in the list must be IN_STOCK';
  END IF;

  START TRANSACTION;

  INSERT INTO shipment (link_id, ship_time, receive_time, status)
  VALUES (v_link, v_now, NULL, 'DISPATCHED');
  SET p_shipment_id = LAST_INSERT_ID();

  INSERT INTO shipment_item (shipment_id, serial_no, received)
  SELECT p_shipment_id, serial_no, FALSE FROM tmp_serials;

  SELECT COALESCE(MAX(event_id), 0) INTO v_before FROM trace_event;

  INSERT INTO trace_event (serial_no, event_type, shipment_id, event_time)
  SELECT serial_no, 'DISPATCHED', p_shipment_id, v_now FROM tmp_serials;

  CALL fill_event_hashes(v_before);

  COMMIT;
END $$

-- ---------------------------------------------------------------------
-- receive_shipment
--   The receiver scans what arrived; p_serials is the scanned list.
--   Each scanned serial falls in one group:
--     on the dispatch list            -> received = 1, RECEIVED event
--     not in pack at all (unknown)    -> RECEIVED event + flag UNKNOWN_SERIAL
--     a real pack, not on this list   -> flag EXTRA_SERIAL (the pack does not move)
--   Each listed pack that was not scanned -> flag MISSING_PACK.
--   Status becomes RECEIVED if everything matched, otherwise PARTIAL.
--   Refuses: SHIPMENT_NOT_FOUND, NOT_IN_TRANSIT.
--   Returns one row: status and the four counts.
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS receive_shipment $$
CREATE PROCEDURE receive_shipment(
  IN p_shipment_id  INT UNSIGNED,
  IN p_serials      TEXT)
BEGIN
  DECLARE v_link      INT UNSIGNED;
  DECLARE v_status    VARCHAR(12);
  DECLARE v_before    BIGINT UNSIGNED;
  DECLARE v_now       DATETIME DEFAULT NOW();
  DECLARE v_received  INT DEFAULT 0;
  DECLARE v_missing   INT DEFAULT 0;
  DECLARE v_unknown   INT DEFAULT 0;
  DECLARE v_extra     INT DEFAULT 0;

  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  SELECT link_id, status INTO v_link, v_status
  FROM shipment WHERE shipment_id = p_shipment_id;

  IF v_link IS NULL THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'SHIPMENT_NOT_FOUND: No shipment with this ID';
  END IF;
  IF v_status <> 'DISPATCHED' THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'NOT_IN_TRANSIT: This shipment has already been received';
  END IF;

  DROP TEMPORARY TABLE IF EXISTS tmp_scanned;
  CREATE TEMPORARY TABLE tmp_scanned (serial_no VARCHAR(20) PRIMARY KEY);
  INSERT INTO tmp_scanned (serial_no)
  SELECT DISTINCT j.s
  FROM JSON_TABLE(CONCAT('["', REPLACE(REPLACE(p_serials, ' ', ''), ',', '","'), '"]'),
                  '$[*]' COLUMNS (s VARCHAR(20) PATH '$')) AS j
  WHERE j.s IS NOT NULL AND j.s <> '';

  -- Serials that get a RECEIVED event: listed ones and unknown ones.
  DROP TEMPORARY TABLE IF EXISTS tmp_receive;
  CREATE TEMPORARY TABLE tmp_receive (serial_no VARCHAR(20) PRIMARY KEY);
  INSERT INTO tmp_receive (serial_no)
  SELECT t.serial_no
  FROM tmp_scanned t
  LEFT JOIN shipment_item si ON si.shipment_id = p_shipment_id AND si.serial_no = t.serial_no
  LEFT JOIN pack p           ON p.serial_no = t.serial_no
  WHERE si.serial_no IS NOT NULL OR p.serial_no IS NULL;

  START TRANSACTION;

  UPDATE shipment_item
  SET received = TRUE
  WHERE shipment_id = p_shipment_id
    AND serial_no IN (SELECT serial_no FROM tmp_scanned);
  SET v_received = ROW_COUNT();

  SELECT COALESCE(MAX(event_id), 0) INTO v_before FROM trace_event;

  INSERT INTO trace_event (serial_no, event_type, shipment_id, event_time)
  SELECT serial_no, 'RECEIVED', p_shipment_id, v_now FROM tmp_receive;

  -- Listed but not scanned (points to the pack's DISPATCHED event)
  INSERT INTO anomaly_flag (rule_code, serial_no, shipment_id, link_id, event_id, severity, detected_at)
  SELECT 'MISSING_PACK', si.serial_no, p_shipment_id, v_link,
         (SELECT MAX(e.event_id) FROM trace_event e
          WHERE e.shipment_id = si.shipment_id AND e.serial_no = si.serial_no
            AND e.event_type = 'DISPATCHED'),
         'MEDIUM', v_now
  FROM shipment_item si
  LEFT JOIN tmp_scanned t ON t.serial_no = si.serial_no
  WHERE si.shipment_id = p_shipment_id AND t.serial_no IS NULL;
  SET v_missing = ROW_COUNT();

  -- Scanned but not a registered pack (points to the RECEIVED event just written)
  INSERT INTO anomaly_flag (rule_code, serial_no, shipment_id, link_id, event_id, severity, detected_at)
  SELECT 'UNKNOWN_SERIAL', e.serial_no, p_shipment_id, v_link, e.event_id, 'CRITICAL', v_now
  FROM trace_event e
  LEFT JOIN pack p ON p.serial_no = e.serial_no
  WHERE e.event_id > v_before
    AND e.shipment_id = p_shipment_id
    AND e.event_type = 'RECEIVED'
    AND p.serial_no IS NULL;
  SET v_unknown = ROW_COUNT();

  -- A real pack that was not on this dispatch list
  INSERT INTO anomaly_flag (rule_code, serial_no, shipment_id, link_id, severity, detected_at)
  SELECT 'EXTRA_SERIAL', t.serial_no, p_shipment_id, v_link, 'HIGH', v_now
  FROM tmp_scanned t
  JOIN pack p ON p.serial_no = t.serial_no
  LEFT JOIN shipment_item si ON si.shipment_id = p_shipment_id AND si.serial_no = t.serial_no
  WHERE si.serial_no IS NULL;
  SET v_extra = ROW_COUNT();

  SET v_status = IF(v_missing + v_unknown + v_extra = 0, 'RECEIVED', 'PARTIAL');

  UPDATE shipment
  SET receive_time = v_now, status = v_status
  WHERE shipment_id = p_shipment_id;

  CALL fill_event_hashes(v_before);

  COMMIT;

  SELECT p_shipment_id AS shipment_id, v_status AS status,
         v_received AS received, v_missing AS missing,
         v_unknown AS unknown_serials, v_extra AS extra_serials;
END $$

-- ---------------------------------------------------------------------
-- sell_pack
--   A retailer sells one pack: a one-pack shipment to CONSUMER
--   (ship = receive = now) and a SOLD event.
--   If the pack is already SOLD this is the clone signal: a SOLD_TWICE
--   flag is saved, nothing is sold, and p_result = 'REFUSED_ALREADY_SOLD'.
--   No error is raised in that case, because an error would roll the flag back.
--   Refuses: NO_LINK, PACK_NOT_FOUND, NOT_OWNER, RECALLED, NOT_IN_STOCK,
--   EXPIRED, and LICENSE_NOT_ACTIVE (trigger 6).
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sell_pack $$
CREATE PROCEDURE sell_pack(
  IN  p_retailer_id  INT UNSIGNED,
  IN  p_serial       VARCHAR(20),
  OUT p_result       VARCHAR(40))
proc: BEGIN
  DECLARE v_link       INT UNSIGNED;
  DECLARE v_status     VARCHAR(12);
  DECLARE v_owner      INT UNSIGNED;
  DECLARE v_expiry     DATE;
  DECLARE v_qc         VARCHAR(10);
  DECLARE v_shipment   INT UNSIGNED;
  DECLARE v_before     BIGINT UNSIGNED;
  DECLARE v_now        DATETIME DEFAULT NOW();

  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  SET p_result = NULL;

  SET v_link = (SELECT l.link_id
                FROM link l
                JOIN participant c ON c.participant_id = l.to_participant
                WHERE l.from_participant = p_retailer_id
                  AND c.participant_type = 'CONSUMER'
                LIMIT 1);
  IF v_link IS NULL THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'NO_LINK: This participant has no link to CONSUMER (not a retailer)';
  END IF;

  SELECT p.status, p.current_owner, b.expiry_date, b.qc_status
    INTO v_status, v_owner, v_expiry, v_qc
  FROM pack p
  JOIN batch b ON b.batch_id = p.batch_id
  WHERE p.serial_no = p_serial;

  IF v_status IS NULL THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'PACK_NOT_FOUND: This serial is not a registered pack';
  END IF;

  IF v_status = 'SOLD' THEN
    START TRANSACTION;
    INSERT INTO anomaly_flag (rule_code, serial_no, link_id, event_id, severity, detected_at)
    VALUES ('SOLD_TWICE', p_serial, v_link,
            (SELECT MAX(event_id) FROM trace_event
             WHERE serial_no = p_serial AND event_type = 'SOLD'),
            'CRITICAL', v_now);
    COMMIT;
    SET p_result = 'REFUSED_ALREADY_SOLD';
    LEAVE proc;
  END IF;

  IF v_owner <> p_retailer_id THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'NOT_OWNER: This retailer does not hold the pack';
  END IF;
  IF v_status = 'RECALLED' OR v_qc = 'RECALLED' THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'RECALLED: This pack belongs to a recalled batch';
  END IF;
  IF v_status <> 'IN_STOCK' THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'NOT_IN_STOCK: The pack must be IN_STOCK to be sold';
  END IF;
  IF v_expiry < CURDATE() THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'EXPIRED: This pack is past its expiry date';
  END IF;

  START TRANSACTION;

  INSERT INTO shipment (link_id, ship_time, receive_time, status)
  VALUES (v_link, v_now, v_now, 'RECEIVED');
  SET v_shipment = LAST_INSERT_ID();

  INSERT INTO shipment_item (shipment_id, serial_no, received)
  VALUES (v_shipment, p_serial, TRUE);

  SELECT COALESCE(MAX(event_id), 0) INTO v_before FROM trace_event;

  INSERT INTO trace_event (serial_no, event_type, shipment_id, event_time)
  VALUES (p_serial, 'SOLD', v_shipment, v_now);

  CALL fill_event_hashes(v_before);

  COMMIT;
  SET p_result = 'SOLD';
END $$

-- ---------------------------------------------------------------------
-- recall_batch
--   1. A recursive CTE starts at the batch's manufacturer and follows the
--      batch's packs shipment by shipment, collecting every participant
--      they reached (hop = number of handovers from the factory).
--   2. Every pack that is not yet SOLD gets a RECALLED event; trigger 5
--      sets its status to RECALLED, the owner stays as it was.
--   3. The batch becomes qc_status RECALLED.
--   Returns one row per participant reached: packs recalled there and
--   packs already sold (the CONSUMER row).
--   Refuses: BATCH_NOT_FOUND, ALREADY_RECALLED.
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS recall_batch $$
CREATE PROCEDURE recall_batch(IN p_batch_id INT UNSIGNED)
BEGIN
  DECLARE v_qc      VARCHAR(10);
  DECLARE v_before  BIGINT UNSIGNED;
  DECLARE v_now     DATETIME DEFAULT NOW();

  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  SET v_qc = (SELECT qc_status FROM batch WHERE batch_id = p_batch_id);
  IF v_qc IS NULL THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'BATCH_NOT_FOUND: No batch with this ID';
  END IF;
  IF v_qc = 'RECALLED' THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'ALREADY_RECALLED: This batch has already been recalled';
  END IF;

  DROP TEMPORARY TABLE IF EXISTS tmp_recall_reach;
  CREATE TEMPORARY TABLE tmp_recall_reach (
    participant_id INT UNSIGNED PRIMARY KEY,
    hop            INT NOT NULL);

  INSERT INTO tmp_recall_reach (participant_id, hop)
  WITH RECURSIVE reach (participant_id, hop) AS (
    -- start: the factory that made the batch
    SELECT b.manufacturer_id, 0
    FROM batch b
    WHERE b.batch_id = p_batch_id
    UNION
    -- step: whoever received this batch's packs from someone already reached
    SELECT l.to_participant, r.hop + 1
    FROM reach r
    JOIN link l           ON l.from_participant = r.participant_id
    JOIN shipment s       ON s.link_id = l.link_id
    JOIN shipment_item si ON si.shipment_id = s.shipment_id
    JOIN pack p           ON p.serial_no = si.serial_no AND p.batch_id = p_batch_id
  )
  SELECT participant_id, MIN(hop) FROM reach GROUP BY participant_id;

  DROP TEMPORARY TABLE IF EXISTS tmp_recall_packs;
  CREATE TEMPORARY TABLE tmp_recall_packs (serial_no VARCHAR(20) PRIMARY KEY);
  INSERT INTO tmp_recall_packs (serial_no)
  SELECT serial_no FROM pack
  WHERE batch_id = p_batch_id AND status NOT IN ('SOLD', 'RECALLED');

  START TRANSACTION;

  SELECT COALESCE(MAX(event_id), 0) INTO v_before FROM trace_event;

  INSERT INTO trace_event (serial_no, event_type, shipment_id, event_time)
  SELECT serial_no, 'RECALLED', NULL, v_now FROM tmp_recall_packs;

  CALL fill_event_hashes(v_before);

  UPDATE batch SET qc_status = 'RECALLED' WHERE batch_id = p_batch_id;

  COMMIT;

  SELECT r.participant_id, p.name, p.participant_type, p.city,
         r.hop AS handovers_from_factory,
         COALESCE(SUM(k.status = 'RECALLED'), 0) AS packs_recalled_here,
         COALESCE(SUM(k.status = 'SOLD'), 0)     AS packs_already_sold
  FROM tmp_recall_reach r
  JOIN participant p ON p.participant_id = r.participant_id
  LEFT JOIN pack k   ON k.batch_id = p_batch_id AND k.current_owner = r.participant_id
  GROUP BY r.participant_id, p.name, p.participant_type, p.city, r.hop
  ORDER BY r.hop, r.participant_id;
END $$

DELIMITER ;

-- Check: should list 8 procedures.
-- SHOW PROCEDURE STATUS WHERE Db = 'pharma_counterfeit_db';
