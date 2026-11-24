-- =====================================================================
-- Pharma Supply Chain DBMS Project
-- 01_schema.sql : database, 15 tables and 1 view
-- Target        : MySQL 8.0.16 or newer (needed for CHECK constraints)
--
-- Run in MySQL Workbench (File > Open SQL Script, then Execute),
-- or from a terminal:  mysql -u root -p < 01_schema.sql
--
-- Tables are created in dependency order: a table that points to
-- another (foreign key) always comes after it.
-- Normalization: see the Normalization Report. All tables are in BCNF
-- except anomaly_flag and injected_counterfeit (deliberately 2NF,
-- write-once logs).
-- =====================================================================

CREATE DATABASE IF NOT EXISTS pharma_counterfeit_db;
USE pharma_counterfeit_db;

-- ---------------------------------------------------------------------
-- OPTIONAL RESET: to rebuild from scratch, remove the "-- " in front of
-- these lines and run them first. This DELETES all tables and their data.
-- Order is the reverse of creation, so foreign keys don't block it.
-- ---------------------------------------------------------------------
-- DROP VIEW  IF EXISTS v_link;
-- DROP TABLE IF EXISTS risk_factor;
-- DROP TABLE IF EXISTS link_risk_score;
-- DROP TABLE IF EXISTS injected_counterfeit;
-- DROP TABLE IF EXISTS anomaly_flag;
-- DROP TABLE IF EXISTS trace_event;
-- DROP TABLE IF EXISTS shipment_item;
-- DROP TABLE IF EXISTS shipment;
-- DROP TABLE IF EXISTS link;
-- DROP TABLE IF EXISTS pack;
-- DROP TABLE IF EXISTS batch_material;
-- DROP TABLE IF EXISTS batch;
-- DROP TABLE IF EXISTS material_lot;
-- DROP TABLE IF EXISTS drug;
-- DROP TABLE IF EXISTS license_history;
-- DROP TABLE IF EXISTS participant;


-- =====================================================================
-- PARTICIPANTS
-- =====================================================================

-- 1. participant
-- Every supplier, manufacturer, distributor, retailer, plus one CONSUMER
-- row for all anonymous end users. latitude/longitude = this
-- participant's own exact location (not the city centre).
CREATE TABLE participant (
  participant_id      INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  name                VARCHAR(120)  NOT NULL,
  participant_type    ENUM('SUPPLIER','MANUFACTURER','DISTRIBUTOR','RETAILER','CONSUMER') NOT NULL,
  license_no          VARCHAR(40)   NULL,
  license_status      ENUM('ACTIVE','SUSPENDED','REVOKED') NULL,
  license_issue_date  DATE          NULL,
  license_valid_till  DATE          NULL,
  city                VARCHAR(60)   NULL,
  state               VARCHAR(60)   NULL,
  latitude            DECIMAL(9,6)  NULL,
  longitude           DECIMAL(9,6)  NULL,
  PRIMARY KEY (participant_id),
  UNIQUE KEY uq_participant_license (license_no),
  CONSTRAINT chk_license_dates CHECK (license_valid_till > license_issue_date)
);

-- 2. license_history
-- One row per license status change (e.g. ACTIVE -> SUSPENDED).
CREATE TABLE license_history (
  history_id      INT UNSIGNED NOT NULL AUTO_INCREMENT,
  participant_id  INT UNSIGNED NOT NULL,
  old_status      ENUM('ACTIVE','SUSPENDED','REVOKED') NOT NULL,
  new_status      ENUM('ACTIVE','SUSPENDED','REVOKED') NOT NULL,
  changed_at      DATETIME     NOT NULL,
  PRIMARY KEY (history_id),
  KEY idx_license_history_participant_time (participant_id, changed_at),
  CONSTRAINT fk_license_history_participant
    FOREIGN KEY (participant_id) REFERENCES participant (participant_id),
  CONSTRAINT chk_license_history_change CHECK (old_status <> new_status)
);


-- =====================================================================
-- PRODUCT
-- =====================================================================

-- 3. drug
-- Product catalog: one row per type of medicine. pack_price = price of
-- one pack (INR).
CREATE TABLE drug (
  drug_id         INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  generic_name    VARCHAR(80)       NOT NULL,
  brand_name      VARCHAR(80)       NOT NULL,
  strength        VARCHAR(30)       NOT NULL,
  dosage_form     ENUM('TABLET','CAPSULE','INJECTION','SYRUP') NOT NULL,
  units_per_pack  SMALLINT UNSIGNED NOT NULL,
  gtin            CHAR(13)          NOT NULL,
  pack_price      DECIMAL(10,2)     NOT NULL,
  high_demand     BOOLEAN           NOT NULL DEFAULT FALSE,
  PRIMARY KEY (drug_id),
  UNIQUE KEY uq_drug_gtin (gtin),
  CONSTRAINT chk_drug_units CHECK (units_per_pack > 0),
  CONSTRAINT chk_drug_price CHECK (pack_price > 0),
  CONSTRAINT chk_drug_gtin  CHECK (gtin REGEXP '^[0-9]{13}$')
);

-- 4. material_lot
-- One raw-material delivery from a supplier to a manufacturer (S->M).
-- Sealed in the ledger as a lot receipt block (lot_hash, ledger_synced).
CREATE TABLE material_lot (
  lot_id                INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  lot_no                VARCHAR(30)   NOT NULL,
  material_name         VARCHAR(80)   NOT NULL,
  quantity_sent_kg      DECIMAL(10,2) NOT NULL,
  quantity_received_kg  DECIMAL(10,2) NOT NULL,
  supplier_id           INT UNSIGNED  NOT NULL,
  manufacturer_id       INT UNSIGNED  NOT NULL,
  received_date         DATE          NOT NULL,
  coa_verified          BOOLEAN       NOT NULL DEFAULT FALSE,
  lot_hash              CHAR(64)      NULL,
  ledger_synced         BOOLEAN       NOT NULL DEFAULT FALSE,
  PRIMARY KEY (lot_id),
  UNIQUE KEY uq_material_lot_supplier_lot (supplier_id, lot_no),
  KEY idx_material_lot_manufacturer (manufacturer_id),
  CONSTRAINT fk_material_lot_supplier
    FOREIGN KEY (supplier_id)     REFERENCES participant (participant_id),
  CONSTRAINT fk_material_lot_manufacturer
    FOREIGN KEY (manufacturer_id) REFERENCES participant (participant_id),
  CONSTRAINT chk_material_lot_sent     CHECK (quantity_sent_kg > 0),
  CONSTRAINT chk_material_lot_received CHECK (quantity_received_kg > 0),
  CONSTRAINT chk_material_lot_hash     CHECK (lot_hash IS NULL OR CHAR_LENGTH(lot_hash) = 64)
);

-- 5. batch
-- One production run of one drug at one factory. batch_hash covers the
-- fixed details plus the sorted list of lot IDs (not qc_status), and is
-- sealed in the production block.
CREATE TABLE batch (
  batch_id         INT UNSIGNED NOT NULL AUTO_INCREMENT,
  drug_id          INT UNSIGNED NOT NULL,
  manufacturer_id  INT UNSIGNED NOT NULL,
  batch_no         VARCHAR(30)  NOT NULL,
  mfg_date         DATE         NOT NULL,
  expiry_date      DATE         NOT NULL,
  quantity         INT UNSIGNED NOT NULL,
  qc_status        ENUM('PENDING','APPROVED','REJECTED','RECALLED') NOT NULL DEFAULT 'PENDING',
  batch_hash       CHAR(64)     NULL,
  ledger_synced    BOOLEAN      NOT NULL DEFAULT FALSE,
  PRIMARY KEY (batch_id),
  UNIQUE KEY uq_batch_manufacturer_batchno (manufacturer_id, batch_no),
  KEY idx_batch_drug (drug_id),
  CONSTRAINT fk_batch_drug
    FOREIGN KEY (drug_id)         REFERENCES drug (drug_id),
  CONSTRAINT fk_batch_manufacturer
    FOREIGN KEY (manufacturer_id) REFERENCES participant (participant_id),
  CONSTRAINT chk_batch_quantity CHECK (quantity > 0),
  CONSTRAINT chk_batch_dates    CHECK (expiry_date > mfg_date),
  CONSTRAINT chk_batch_hash     CHECK (batch_hash IS NULL OR CHAR_LENGTH(batch_hash) = 64)
);

-- 6. batch_material
-- Many-to-many: which lots each batch was made from.
CREATE TABLE batch_material (
  batch_id  INT UNSIGNED NOT NULL,
  lot_id    INT UNSIGNED NOT NULL,
  PRIMARY KEY (batch_id, lot_id),
  KEY idx_batch_material_lot (lot_id),
  CONSTRAINT fk_batch_material_batch
    FOREIGN KEY (batch_id) REFERENCES batch (batch_id),
  CONSTRAINT fk_batch_material_lot
    FOREIGN KEY (lot_id)   REFERENCES material_lot (lot_id)
);

-- 7. pack
-- One physical strip/box/bottle with a unique serial in its QR code.
-- current_owner and status are kept in sync with trace_event by a trigger.
CREATE TABLE pack (
  serial_no      VARCHAR(20)  NOT NULL,
  batch_id       INT UNSIGNED NOT NULL,
  current_owner  INT UNSIGNED NOT NULL,
  status         ENUM('IN_STOCK','IN_TRANSIT','SOLD','RECALLED') NOT NULL DEFAULT 'IN_STOCK',
  PRIMARY KEY (serial_no),
  KEY idx_pack_batch (batch_id),
  KEY idx_pack_owner_status (current_owner, status),
  CONSTRAINT fk_pack_batch
    FOREIGN KEY (batch_id)      REFERENCES batch (batch_id),
  CONSTRAINT fk_pack_owner
    FOREIGN KEY (current_owner) REFERENCES participant (participant_id)
);


-- =====================================================================
-- MOVEMENT
-- =====================================================================

-- 8. link
-- One row per trading pair (e.g. M3 -> D4). The stage (S_M, M_D, D_R,
-- R_E) is not stored; it comes from the view v_link (2NF fix).
CREATE TABLE link (
  link_id           INT UNSIGNED NOT NULL AUTO_INCREMENT,
  from_participant  INT UNSIGNED NOT NULL,
  to_participant    INT UNSIGNED NOT NULL,
  PRIMARY KEY (link_id),
  UNIQUE KEY uq_link_pair (from_participant, to_participant),
  KEY idx_link_to (to_participant),
  CONSTRAINT fk_link_from FOREIGN KEY (from_participant) REFERENCES participant (participant_id),
  CONSTRAINT fk_link_to   FOREIGN KEY (to_participant)   REFERENCES participant (participant_id),
  CONSTRAINT chk_link_not_self CHECK (from_participant <> to_participant)
);

-- 9. shipment
-- One handover of a group of packs on one link. A sale = a one-pack
-- shipment from a retailer to the CONSUMER row. Sender and receiver come
-- from link (3NF fix).
CREATE TABLE shipment (
  shipment_id   INT UNSIGNED NOT NULL AUTO_INCREMENT,
  link_id       INT UNSIGNED NOT NULL,
  ship_time     DATETIME     NOT NULL,
  receive_time  DATETIME     NULL,
  status        ENUM('DISPATCHED','RECEIVED','PARTIAL','REJECTED') NOT NULL DEFAULT 'DISPATCHED',
  PRIMARY KEY (shipment_id),
  KEY idx_shipment_link_time (link_id, ship_time),
  KEY idx_shipment_ship_time (ship_time),
  CONSTRAINT fk_shipment_link
    FOREIGN KEY (link_id) REFERENCES link (link_id),
  CONSTRAINT chk_shipment_times CHECK (receive_time IS NULL OR receive_time >= ship_time),
  CONSTRAINT chk_shipment_status_time CHECK (
       (status = 'DISPATCHED' AND receive_time IS NULL)
    OR (status IN ('RECEIVED','PARTIAL') AND receive_time IS NOT NULL)
    OR (status = 'REJECTED')
  )
);

-- 10. shipment_item
-- The dispatch list: which packs are in each shipment.
-- received = TRUE once the receiver confirms that pack arrived.
CREATE TABLE shipment_item (
  shipment_id  INT UNSIGNED NOT NULL,
  serial_no    VARCHAR(20)  NOT NULL,
  received     BOOLEAN      NOT NULL DEFAULT FALSE,
  PRIMARY KEY (shipment_id, serial_no),
  KEY idx_shipment_item_serial (serial_no),
  CONSTRAINT fk_shipment_item_shipment
    FOREIGN KEY (shipment_id) REFERENCES shipment (shipment_id),
  CONSTRAINT fk_shipment_item_pack
    FOREIGN KEY (serial_no)   REFERENCES pack (serial_no)
);

-- 11. trace_event
-- Append-only history: one row per thing that happens to one pack.
-- serial_no has NO foreign key on purpose, so fake/unknown serials can
-- still be recorded and flagged. Sender, receiver and city come through
-- joins (3NF fix). event_hash is filled right after insert, because it
-- includes event_id.
CREATE TABLE trace_event (
  event_id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  serial_no      VARCHAR(20)     NOT NULL,
  event_type     ENUM('MANUFACTURED','DISPATCHED','RECEIVED','SOLD','RECALLED') NOT NULL,
  shipment_id    INT UNSIGNED    NULL,
  event_time     DATETIME        NOT NULL,
  event_hash     CHAR(64)        NULL,
  ledger_synced  BOOLEAN         NOT NULL DEFAULT FALSE,
  PRIMARY KEY (event_id),
  KEY idx_trace_event_serial_time (serial_no, event_time),
  KEY idx_trace_event_time        (event_time),
  KEY idx_trace_event_shipment    (shipment_id),
  KEY idx_trace_event_unsynced    (ledger_synced),
  CONSTRAINT fk_trace_event_shipment
    FOREIGN KEY (shipment_id) REFERENCES shipment (shipment_id),
  CONSTRAINT chk_trace_event_shipment CHECK (
       (event_type IN ('MANUFACTURED','RECALLED')      AND shipment_id IS NULL)
    OR (event_type IN ('DISPATCHED','RECEIVED','SOLD') AND shipment_id IS NOT NULL)
  ),
  CONSTRAINT chk_trace_event_hash CHECK (event_hash IS NULL OR CHAR_LENGTH(event_hash) = 64)
);


-- =====================================================================
-- DETECTION, SIMULATION AND AI
-- =====================================================================

-- 12. anomaly_flag
-- One row each time a detection rule finds something suspicious.
-- Deliberately 2NF: write-once log (see Normalization Report).
CREATE TABLE anomaly_flag (
  flag_id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  rule_code    VARCHAR(40)     NOT NULL,
  serial_no    VARCHAR(20)     NULL,
  shipment_id  INT UNSIGNED    NULL,
  link_id      INT UNSIGNED    NULL,
  event_id     BIGINT UNSIGNED NULL,
  lot_id       INT UNSIGNED    NULL,
  severity     ENUM('LOW','MEDIUM','HIGH','CRITICAL') NOT NULL DEFAULT 'MEDIUM',
  detected_at  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  resolved     BOOLEAN         NOT NULL DEFAULT FALSE,
  PRIMARY KEY (flag_id),
  KEY idx_anomaly_flag_serial (serial_no),
  KEY idx_anomaly_flag_rule   (rule_code),
  KEY idx_anomaly_flag_open   (resolved, detected_at),
  CONSTRAINT fk_anomaly_flag_shipment FOREIGN KEY (shipment_id) REFERENCES shipment (shipment_id),
  CONSTRAINT fk_anomaly_flag_link     FOREIGN KEY (link_id)     REFERENCES link (link_id),
  CONSTRAINT fk_anomaly_flag_event    FOREIGN KEY (event_id)    REFERENCES trace_event (event_id),
  CONSTRAINT fk_anomaly_flag_lot      FOREIGN KEY (lot_id)      REFERENCES material_lot (lot_id)
);

-- 13. injected_counterfeit
-- SIMULATION ONLY: the answer key. Detection rules must never read it.
-- Deliberately 2NF: write-once record (see Normalization Report).
CREATE TABLE injected_counterfeit (
  inject_id      INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  scenario_type  ENUM('FAKE_MATERIAL','INVENTED_SERIAL','CLONED_SERIAL','TRANSIT_SWAP',
                      'UNLICENSED_HANDLER','STAGE_SKIPPED','RECORD_TAMPERED') NOT NULL,
  link_id        INT UNSIGNED    NULL,
  shipment_id    INT UNSIGNED    NULL,
  serial_no      VARCHAR(20)     NULL,
  lot_id         INT UNSIGNED    NULL,
  event_id       BIGINT UNSIGNED NULL,
  injected_at    DATETIME        NOT NULL,
  PRIMARY KEY (inject_id),
  KEY idx_injected_serial   (serial_no),
  KEY idx_injected_scenario (scenario_type),
  CONSTRAINT fk_injected_link     FOREIGN KEY (link_id)     REFERENCES link (link_id),
  CONSTRAINT fk_injected_shipment FOREIGN KEY (shipment_id) REFERENCES shipment (shipment_id),
  CONSTRAINT fk_injected_lot      FOREIGN KEY (lot_id)      REFERENCES material_lot (lot_id),
  CONSTRAINT fk_injected_event    FOREIGN KEY (event_id)    REFERENCES trace_event (event_id)
);

-- 14. link_risk_score
-- AI output: counterfeit-risk probability per trading pair, per model run.
CREATE TABLE link_risk_score (
  score_id       INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  link_id        INT UNSIGNED  NOT NULL,
  risk_score     DECIMAL(5,4)  NOT NULL,
  model_version  VARCHAR(30)   NOT NULL,
  scored_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (score_id),
  KEY idx_link_risk_link_time (link_id, scored_at),
  CONSTRAINT fk_link_risk_link FOREIGN KEY (link_id) REFERENCES link (link_id),
  CONSTRAINT chk_link_risk_range CHECK (risk_score BETWEEN 0 AND 1)
);

-- 15. risk_factor
-- The reasons behind each score, one row per feature (1NF fix: replaces
-- a JSON list). weight > 0 raised the risk, weight < 0 lowered it.
CREATE TABLE risk_factor (
  score_id      INT UNSIGNED NOT NULL,
  feature_name  VARCHAR(40)  NOT NULL,
  weight        DECIMAL(7,4) NOT NULL,
  PRIMARY KEY (score_id, feature_name),
  CONSTRAINT fk_risk_factor_score
    FOREIGN KEY (score_id) REFERENCES link_risk_score (score_id)
);


-- =====================================================================
-- VIEWS
-- =====================================================================

-- v_link: each link with its stage, worked out from the sender's type.
CREATE OR REPLACE VIEW v_link AS
SELECT l.link_id,
       l.from_participant,
       l.to_participant,
       CASE p.participant_type
         WHEN 'SUPPLIER'     THEN 'S_M'
         WHEN 'MANUFACTURER' THEN 'M_D'
         WHEN 'DISTRIBUTOR'  THEN 'D_R'
         WHEN 'RETAILER'     THEN 'R_E'
       END AS link_type
FROM link l
JOIN participant p ON p.participant_id = l.from_participant;
