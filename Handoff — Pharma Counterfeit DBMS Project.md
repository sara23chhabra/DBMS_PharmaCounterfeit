# Handoff — Pharma Counterfeit DBMS Project

Nov 23, 2026 · @Vineet

## Read this first: how the user wants to work

The user is a student building this for a DBMS course and wants to understand every part. Early in the first chat, a lot was generated at once and they were upset. Since then, this way of working has gone well:

- **One item at a time.** One table, one trigger, one procedure per message. Wait for them to say "next".
- **Give the query, they run it themselves.** They paste each query into MySQL, run it, check it with DESCRIBE, then confirm. Do not run things on their behalf or produce many files at once.
- **Explain every decision.** For each column, key, rule or index: what it is and why. Use plain words and small examples from this project.
- **Ask before deciding.** When there is a real choice, lay out the options with the trade-off, give a recommendation, and let them pick. Do not silently decide.
- **Never assume what they have run.** Give the full query each time; if a table may already exist, give both the DROP/ALTER route and the CREATE route. They said: "dont assume i made table ill tell you if i did".
- **Admit mistakes plainly** and correct them; they appreciated this.
- **The original outline PDF is not binding.** They said its contents can be changed after discussion.
- **Keep it simple.** They prefer dropping unused columns and edge cases ("no need for edge cases").

## Project basics

- **What:** a simulated pharma supply chain (Supplier → Manufacturer → Distributor → Retailer → Consumer) for counterfeit detection, with three layers: a MySQL database (main focus), a hash-chain ledger in MongoDB, and an AI model that scores trading links for counterfeit risk.
- **Database:** MySQL 8.0.16+, named `pharma_counterfeit_db`. MongoDB collections planned: `ledger_blocks`, `scan_logs`.
- **Code:** Python for the application layer, simulator, ledger and ML (scikit-learn, pandas; pymongo).
- **Team:** the user works with a team and a GitHub repository; all SQL goes into files in the repo.
- **Source outline:** the PDF "Pharma Supply Chain DBMS Project" in the project files. Many details have since changed; the decision log below wins over the PDF.

## Current state

| Item | Status |
| --- | --- |
| 15 tables + view v\_link | Created by the user in MySQL, one at a time |
| `01_schema.sql` (final CREATE statements, reset block commented out) | Written and delivered; in the repo plan |
| Testing 01\_schema.sql | In progress: the user is running it in a test database `pharma_counterfeit_test` and comparing it with their real database via information\_schema queries. Result not yet reported. |
| Normalization Report, Table Reference, End-to-End Walkthrough | Written (links under Related documents) |
| Triggers, procedures, other views, roles | Not started |
| Data generator (simulator) | Not started for the new schema; the old one is obsolete |
| Ledger, verification, detection, AI | Not started |

**First thing to do in a new chat:** ask whether the schema comparison returned any differences. If yes, explain each and help them fix it (rebuilding the real database from the file is safe; its tables are empty).

## Decision log

Each row is a decision the user made after discussion. Do not reverse any without asking.

| Area | Decision | Why |
| --- | --- | --- |
| Participants | No subtype tables (supplier, manufacturer, distributor, retailer dropped); 18 → 14 tables | Their extra columns were unused; participant\_type is enough |
| participant | Keep latitude and longitude, defined as each participant's own exact location | AI distance feature; keeps BCNF |
| Supplier ingredients | No ingredient column; material\_lot.material\_name records it per delivery | Avoids a list in a cell; already derivable |
| Type correctness | Use triggers to check participant types on material\_lot, batch and link ("option A") | FKs only point to participant |
| drug | dosage\_form = TABLET, CAPSULE, INJECTION, SYRUP; tablets\_per\_pack renamed units\_per\_pack; unit\_price renamed pack\_price | Supports injections; clearer names |
| material\_lot | Added quantity\_sent\_kg and quantity\_received\_kg (kg only); received > sent is a fake-material signal, less is a loss anomaly | Detect scenario 1 |
| material\_lot | Lots get their own ledger block (lot receipt block): lot\_hash + ledger\_synced | Counterfeits can enter at S→M |
| batch | Batch details sealed in the production block: batch\_hash + ledger\_synced; hash covers fixed fields + sorted lot IDs, not qc\_status | Catches insider + counterfeiter changing expiry or lots together |
| batch\_material | No quantity\_used\_kg | Unneeded extra |
| pack | Removed FLAGGED from status; no flag column on pack | A pack can have many flags; they live in anomaly\_flag |
| link | link\_type removed (2NF); stage comes from view v\_link | Sender alone decided it |
| shipment | Removed from\_participant, to\_participant (3NF) and transporter (unused) | Derivable via link |
| shipment\_item | Keep received column | Simple missing-pack query |
| trace\_event | Keep serial\_no WITHOUT a FK | Fake serials must still be recorded and flagged |
| trace\_event | Removed from\_participant, to\_participant, location\_city (3NF) | Derivable via joins; must still be included in the event hash |
| trace\_event | Added RECALLED event type (no shipment, like MANUFACTURED) and a recall block | Recalls become part of the sealed history |
| trace\_event | No IN\_STOCK event | States are derived from events |
| anomaly\_flag | Removed chain\_stage; added lot\_id | Stage via link; flags point to the exact lot |
| injected\_counterfeit | One row per serial (no ranges); added shipment\_id and event\_id | Precise matching against flags |
| link\_risk\_score | Store only existing links ("option A"); never-traded pairs scored live, not saved | No edge cases needed |
| risk\_factor | New table replaces JSON top\_factors (1NF) | Teacher may check 1NF |
| QR / relabelling | No extra columns; verification compares QR fields (GTIN, batch no, expiry) with the database | Physical relabelling is caught at scan |
| Threat model | Normally only the admin touches the DB, but the ledger proves nobody changed history, including an insider | Matches the tamper demo |
| Normalization | Target BCNF; anomaly\_flag and injected\_counterfeit deliberately 2NF (write-once logs) | Documented in the Normalization Report |

## Next steps, in order

Work through these one item at a time, explaining and asking as described above.

1. **Confirm the schema test** (comparison of `pharma_counterfeit_test` with `pharma_counterfeit_db`); then the user drops the test database and pushes `01_schema.sql`.
2. **Triggers** (`02_triggers.sql`), one at a time:
   1. Type check on material\_lot (supplier is SUPPLIER, manufacturer is MANUFACTURER)
   2. Type check on batch (manufacturer is MANUFACTURER)
   3. Type check on link (receiver type fits sender type; RETAILER → CONSUMER)
   4. Append-only trace\_event: block UPDATE and DELETE, except filling a NULL event\_hash once and setting ledger\_synced to TRUE
   5. Pack state: after a trace\_event insert, set pack.current\_owner and status (owner found via shipment → link; RECALLED keeps the owner)
   6. License check at dispatch (sender's license must be ACTIVE)
   7. license\_history written when participant.license\_status changes
3. **Stored procedures** (`03_procedures.sql`): create\_batch (batch + batch\_material in one transaction, then batch\_hash), generate\_packs (packs + MANUFACTURED events + hashes), dispatch\_shipment, receive\_shipment (missing / extra / unknown serials → flags), sell\_pack (clone flag if already sold), recall\_batch (recursive CTE, RECALLED events, qc\_status RECALLED).
4. **Views** (`04_views.sql`): v\_serial\_journey (LEFT JOINs + COALESCE for sender/receiver/city), v\_link\_stats, v\_open\_flags, one per actor type. v\_link already exists.
5. **Roles** (`05_roles.sql`): per-actor visibility; detection account denied on injected\_counterfeit.
6. **Data generator**, rebuilt for the new schema: \~4 suppliers, 3 manufacturers, 8 distributors, \~40 retailers, 1 CONSUMER; 10 drugs; 100–200 batches; \~50,000 packs; \~9 months (months 1–6 features, 7–9 labels); Indian cities with exact coordinates; fixed random seed. Normal flow first, then counterfeit injection.
7. **Ledger writer** in Python (six block types, idempotent upserts), then consumer verification, detection rules with precision/recall, reconciliation and tamper demo.
8. **AI:** feature extraction to link\_features.csv, logistic regression then Random Forest/XGBoost, write link\_risk\_score and risk\_factor, pair-scoring interface.
9. Optional: dashboard; real blockchain upgrade (Hardhat/Solidity) only after everything else works.

## Pitfalls and technical notes

- **Obsolete files:** at the very start of the first chat, an `01_schema.sql` (18 tables), `generate_data.py`, `hashing.py`, `99_sanity_checks.sql`, README and .gitignore were generated for the OLD design. None match the current schema. Do not reuse them as-is; the hashing canonical-string idea can be reused, updated for joins.
- **Hashes need the auto-increment ID**, which exists only after INSERT: insert the row, then UPDATE the hash. The append-only trigger must allow exactly this.
- **Canonical hash string:** fields joined with '|', NULL written as '', DATETIME as 'YYYY-MM-DD HH:MM:SS', so Python and MySQL's SHA2(..., 256) agree. Use CONCAT with IFNULL, not CONCAT\_WS (it skips NULLs).
- **Event hash must include sender and receiver** fetched through shipment → link (or batch → manufacturer), since they are no longer columns on trace\_event.
- **Batch hash:** lot IDs sorted ascending; exclude qc\_status.
- **Triggers vs bulk data loading:** decide with the user whether the simulator inserts through the procedures (triggers fire, slower) or bulk-inserts with triggers temporarily disabled. Not yet discussed.
- **Seed data size:** \~50,000 packs produced a \~55 MB SQL file before, over GitHub's 50 MB warning; commit the generator and a fixed seed, git-ignore the output.
- **Stage labels:** use S\_M, M\_D, D\_R, R\_E (ASCII), not arrows.
- **MANUFACTURED events** have no shipment; the manufacturer comes from pack → batch. **RECALLED events** have no shipment; the holder comes from the pack's previous event.
- **CHECK constraints** need MySQL 8.0.16 or newer.

## Related documents and files

| Document | What it holds |
| --- | --- |
| [Normalization Report](https://claude.ai/artifact/QSmk1n48ZL3wCSA5GQC8Nx) | Normal forms explained, per-table analysis, design changes, controlled denormalization |
| [Table Reference](https://claude.ai/artifact/7tb8TVzHFnJzCr1qASDNX6) | Every table's purpose, columns, PK, FKs, rules, indexes and relationships |
| [End-to-End System Walkthrough](https://claude.ai/artifact/AgKniM6LsmEzvi9uMDXMEu) | How DBMS, ledger and AI work together; architecture diagram; scenarios; AI pipeline |
| `01_schema.sql` | The final schema; also copied in full in the appendix below and saved to the "DBMS" project |
| Project outline PDF | The original plan (superseded where the decision log differs) |

## Appendix: current schema (01\_schema.sql)

These are the same statements as the delivered file, with its comments and commented-out reset block left out. The user's live database was built from the same queries step by step.

```sql
CREATE DATABASE IF NOT EXISTS pharma_counterfeit_db;
USE pharma_counterfeit_db;

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

CREATE TABLE risk_factor (
  score_id      INT UNSIGNED NOT NULL,
  feature_name  VARCHAR(40)  NOT NULL,
  weight        DECIMAL(7,4) NOT NULL,
  PRIMARY KEY (score_id, feature_name),
  CONSTRAINT fk_risk_factor_score
    FOREIGN KEY (score_id) REFERENCES link_risk_score (score_id)
);

CREATE OR REPLACE VIEW v_link AS
SELECT l.link_id, l.from_participant, l.to_participant,
       CASE p.participant_type
         WHEN 'SUPPLIER'     THEN 'S_M'
         WHEN 'MANUFACTURER' THEN 'M_D'
         WHEN 'DISTRIBUTOR'  THEN 'D_R'
         WHEN 'RETAILER'     THEN 'R_E'
       END AS link_type
FROM link l
JOIN participant p ON p.participant_id = l.from_participant;
```
