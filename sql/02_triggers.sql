-- =====================================================================
-- Pharma Supply Chain DBMS Project
-- 02_triggers.sql : the 7 trigger rules (Person A)
--
-- Run after 01_schema.sql. Safe to run again: every trigger is dropped
-- and re-created.
--
-- Two switches (session variables, normally NULL):
--   @seed_loading = 1  -> all triggers stay quiet (set by seed_data.sql)
--   @tamper_demo  = 1  -> the append-only rule on trace_event is off
--                         (used only by the tamper demo, to play an insider)
--
-- Errors are raised as  SIGNAL SQLSTATE '45000'  with a message of the
-- form  'CODE: plain sentence'.
--
-- MySQL allows one event per trigger, so rules that must hold on both
-- INSERT and UPDATE appear as two triggers with the same body.
-- =====================================================================

USE pharma_counterfeit_db;

DELIMITER $$

-- ---------------------------------------------------------------------
-- 1. material_lot: supplier must be a SUPPLIER, manufacturer a MANUFACTURER
--    (the foreign keys only prove the ID is some participant)
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_material_lot_type_ins $$
CREATE TRIGGER trg_material_lot_type_ins
BEFORE INSERT ON material_lot
FOR EACH ROW
BEGIN
  IF @seed_loading IS NULL THEN
    IF (SELECT participant_type FROM participant
        WHERE participant_id = NEW.supplier_id) <> 'SUPPLIER' THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'WRONG_PARTICIPANT_TYPE: supplier_id must be a SUPPLIER';
    END IF;
    IF (SELECT participant_type FROM participant
        WHERE participant_id = NEW.manufacturer_id) <> 'MANUFACTURER' THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'WRONG_PARTICIPANT_TYPE: manufacturer_id must be a MANUFACTURER';
    END IF;
  END IF;
END $$

DROP TRIGGER IF EXISTS trg_material_lot_type_upd $$
CREATE TRIGGER trg_material_lot_type_upd
BEFORE UPDATE ON material_lot
FOR EACH ROW
BEGIN
  IF @seed_loading IS NULL THEN
    IF (SELECT participant_type FROM participant
        WHERE participant_id = NEW.supplier_id) <> 'SUPPLIER' THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'WRONG_PARTICIPANT_TYPE: supplier_id must be a SUPPLIER';
    END IF;
    IF (SELECT participant_type FROM participant
        WHERE participant_id = NEW.manufacturer_id) <> 'MANUFACTURER' THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'WRONG_PARTICIPANT_TYPE: manufacturer_id must be a MANUFACTURER';
    END IF;
  END IF;
END $$

-- ---------------------------------------------------------------------
-- 2. batch: manufacturer must be a MANUFACTURER
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_batch_type_ins $$
CREATE TRIGGER trg_batch_type_ins
BEFORE INSERT ON batch
FOR EACH ROW
BEGIN
  IF @seed_loading IS NULL THEN
    IF (SELECT participant_type FROM participant
        WHERE participant_id = NEW.manufacturer_id) <> 'MANUFACTURER' THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'WRONG_PARTICIPANT_TYPE: manufacturer_id must be a MANUFACTURER';
    END IF;
  END IF;
END $$

DROP TRIGGER IF EXISTS trg_batch_type_upd $$
CREATE TRIGGER trg_batch_type_upd
BEFORE UPDATE ON batch
FOR EACH ROW
BEGIN
  IF @seed_loading IS NULL THEN
    IF (SELECT participant_type FROM participant
        WHERE participant_id = NEW.manufacturer_id) <> 'MANUFACTURER' THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'WRONG_PARTICIPANT_TYPE: manufacturer_id must be a MANUFACTURER';
    END IF;
  END IF;
END $$

-- ---------------------------------------------------------------------
-- 3. link: only the four allowed pairs
--    SUPPLIER -> MANUFACTURER -> DISTRIBUTOR -> RETAILER -> CONSUMER
--    (if an ID does not exist the types are NULL, the IF is not taken,
--     and the foreign key rejects the row instead)
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_link_type_ins $$
CREATE TRIGGER trg_link_type_ins
BEFORE INSERT ON link
FOR EACH ROW
BEGIN
  DECLARE v_from VARCHAR(20);
  DECLARE v_to   VARCHAR(20);
  IF @seed_loading IS NULL THEN
    SET v_from = (SELECT participant_type FROM participant WHERE participant_id = NEW.from_participant);
    SET v_to   = (SELECT participant_type FROM participant WHERE participant_id = NEW.to_participant);
    IF NOT (   (v_from = 'SUPPLIER'     AND v_to = 'MANUFACTURER')
            OR (v_from = 'MANUFACTURER' AND v_to = 'DISTRIBUTOR')
            OR (v_from = 'DISTRIBUTOR'  AND v_to = 'RETAILER')
            OR (v_from = 'RETAILER'     AND v_to = 'CONSUMER')) THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'INVALID_LINK: allowed pairs are S->M, M->D, D->R and R->CONSUMER';
    END IF;
  END IF;
END $$

DROP TRIGGER IF EXISTS trg_link_type_upd $$
CREATE TRIGGER trg_link_type_upd
BEFORE UPDATE ON link
FOR EACH ROW
BEGIN
  DECLARE v_from VARCHAR(20);
  DECLARE v_to   VARCHAR(20);
  IF @seed_loading IS NULL THEN
    SET v_from = (SELECT participant_type FROM participant WHERE participant_id = NEW.from_participant);
    SET v_to   = (SELECT participant_type FROM participant WHERE participant_id = NEW.to_participant);
    IF NOT (   (v_from = 'SUPPLIER'     AND v_to = 'MANUFACTURER')
            OR (v_from = 'MANUFACTURER' AND v_to = 'DISTRIBUTOR')
            OR (v_from = 'DISTRIBUTOR'  AND v_to = 'RETAILER')
            OR (v_from = 'RETAILER'     AND v_to = 'CONSUMER')) THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'INVALID_LINK: allowed pairs are S->M, M->D, D->R and R->CONSUMER';
    END IF;
  END IF;
END $$

-- ---------------------------------------------------------------------
-- 4. trace_event is append-only
--    Allowed changes to an existing row, and nothing else:
--      event_hash     NULL  -> a value   (once; the ID exists only after INSERT)
--      ledger_synced  FALSE -> TRUE      (the ledger writer)
--    <=> is the NULL-safe "equals" (NULL <=> NULL is true).
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_trace_event_no_update $$
CREATE TRIGGER trg_trace_event_no_update
BEFORE UPDATE ON trace_event
FOR EACH ROW
BEGIN
  IF @seed_loading IS NULL AND @tamper_demo IS NULL THEN
    IF NOT (    NEW.event_id    <=> OLD.event_id
            AND NEW.serial_no   <=> OLD.serial_no
            AND NEW.event_type  <=> OLD.event_type
            AND NEW.shipment_id <=> OLD.shipment_id
            AND NEW.event_time  <=> OLD.event_time) THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'APPEND_ONLY: trace_event rows cannot be changed';
    END IF;
    IF OLD.event_hash IS NOT NULL AND NOT (NEW.event_hash <=> OLD.event_hash) THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'APPEND_ONLY: event_hash can be set only once';
    END IF;
    IF OLD.ledger_synced = TRUE AND NEW.ledger_synced = FALSE THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'APPEND_ONLY: ledger_synced cannot be switched back';
    END IF;
  END IF;
END $$

DROP TRIGGER IF EXISTS trg_trace_event_no_delete $$
CREATE TRIGGER trg_trace_event_no_delete
BEFORE DELETE ON trace_event
FOR EACH ROW
BEGIN
  IF @seed_loading IS NULL AND @tamper_demo IS NULL THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'APPEND_ONLY: trace_event rows cannot be deleted';
  END IF;
END $$

-- ---------------------------------------------------------------------
-- 5. Pack state follows the events
--    pack.current_owner and pack.status are copies of "what the latest
--    event says"; this trigger keeps them in step.
--      MANUFACTURED -> owner = the batch's manufacturer, IN_STOCK
--      DISPATCHED   -> IN_TRANSIT (owner stays the sender until receipt)
--      RECEIVED     -> owner = the link's receiver, IN_STOCK
--      SOLD         -> owner = the link's receiver (CONSUMER), SOLD
--      RECALLED     -> RECALLED, owner unchanged
--    A serial that is not in pack (a fake) matches no row: nothing happens.
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_pack_state $$
CREATE TRIGGER trg_pack_state
AFTER INSERT ON trace_event
FOR EACH ROW
BEGIN
  DECLARE v_receiver INT UNSIGNED;
  IF @seed_loading IS NULL THEN
    IF NEW.event_type = 'MANUFACTURED' THEN
      UPDATE pack p
      JOIN batch b ON b.batch_id = p.batch_id
      SET p.current_owner = b.manufacturer_id, p.status = 'IN_STOCK'
      WHERE p.serial_no = NEW.serial_no;

    ELSEIF NEW.event_type = 'DISPATCHED' THEN
      UPDATE pack SET status = 'IN_TRANSIT'
      WHERE serial_no = NEW.serial_no;

    ELSEIF NEW.event_type IN ('RECEIVED', 'SOLD') THEN
      SET v_receiver = (SELECT l.to_participant
                        FROM shipment s
                        JOIN link l ON l.link_id = s.link_id
                        WHERE s.shipment_id = NEW.shipment_id);
      UPDATE pack
      SET current_owner = v_receiver,
          status = IF(NEW.event_type = 'SOLD', 'SOLD', 'IN_STOCK')
      WHERE serial_no = NEW.serial_no;

    ELSEIF NEW.event_type = 'RECALLED' THEN
      UPDATE pack SET status = 'RECALLED'
      WHERE serial_no = NEW.serial_no;
    END IF;
  END IF;
END $$

-- ---------------------------------------------------------------------
-- 6. License check at dispatch
--    A shipment (a sale is a shipment too) can start only if the sender's
--    license is ACTIVE.
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_shipment_license $$
CREATE TRIGGER trg_shipment_license
BEFORE INSERT ON shipment
FOR EACH ROW
BEGIN
  IF @seed_loading IS NULL THEN
    IF (SELECT p.license_status
        FROM link l
        JOIN participant p ON p.participant_id = l.from_participant
        WHERE l.link_id = NEW.link_id) <> 'ACTIVE' THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'LICENSE_NOT_ACTIVE: Sender license must be ACTIVE to dispatch';
    END IF;
  END IF;
END $$

-- ---------------------------------------------------------------------
-- 7. License history
--    Every change of participant.license_status is logged automatically.
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_license_history $$
CREATE TRIGGER trg_license_history
AFTER UPDATE ON participant
FOR EACH ROW
BEGIN
  IF @seed_loading IS NULL THEN
    IF OLD.license_status IS NOT NULL AND NEW.license_status IS NOT NULL
       AND OLD.license_status <> NEW.license_status THEN
      INSERT INTO license_history (participant_id, old_status, new_status, changed_at)
      VALUES (NEW.participant_id, OLD.license_status, NEW.license_status, NOW());
    END IF;
  END IF;
END $$

DELIMITER ;

-- Check: should list 11 triggers (rules 1-4 need two triggers each).
-- SHOW TRIGGERS;
