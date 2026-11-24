
USE pharma_counterfeit_db;

-- create the independent database roles
CREATE ROLE IF NOT EXISTS 'role_admin'@'%';
CREATE ROLE IF NOT EXISTS 'role_detection'@'%';
CREATE ROLE IF NOT EXISTS 'role_ledger'@'%';
CREATE ROLE IF NOT EXISTS 'role_readonly'@'%';

-- give the admin full privileges on this project database
GRANT ALL PRIVILEGES
ON pharma_counterfeit_db.*
TO 'role_admin'@'%';

-- allow detection to read all real project tables
GRANT SELECT ON pharma_counterfeit_db.participant
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_db.license_history
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_db.drug
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_db.material_lot
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_db.batch
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_db.batch_material
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_db.pack
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_db.link
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_db.shipment
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_db.shipment_item
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_db.trace_event
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_db.anomaly_flag
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_db.link_risk_score
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_db.risk_factor
TO 'role_detection'@'%';

-- allow detection to insert anomaly flags
GRANT INSERT ON pharma_counterfeit_db.anomaly_flag
TO 'role_detection'@'%';

-- allow the ledger role to read real project tables
GRANT SELECT ON pharma_counterfeit_db.participant
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_db.license_history
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_db.drug
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_db.material_lot
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_db.batch
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_db.batch_material
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_db.pack
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_db.link
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_db.shipment
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_db.shipment_item
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_db.trace_event
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_db.anomaly_flag
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_db.link_risk_score
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_db.risk_factor
TO 'role_ledger'@'%';

-- allow the ledger role to update only the ledger_synced column
GRANT UPDATE (ledger_synced)
ON pharma_counterfeit_db.material_lot
TO 'role_ledger'@'%';

GRANT UPDATE (ledger_synced)
ON pharma_counterfeit_db.batch
TO 'role_ledger'@'%';

GRANT UPDATE (ledger_synced)
ON pharma_counterfeit_db.trace_event
TO 'role_ledger'@'%';

-- allow read-only access to project views
GRANT SELECT ON pharma_counterfeit_db.v_link
TO 'role_readonly'@'%';

GRANT SELECT ON pharma_counterfeit_db.v_serial_journey
TO 'role_readonly'@'%';

GRANT SELECT ON pharma_counterfeit_db.v_link_stats
TO 'role_readonly'@'%';

GRANT SELECT ON pharma_counterfeit_db.v_open_flags
TO 'role_readonly'@'%';

GRANT SELECT ON pharma_counterfeit_db.v_supplier
TO 'role_readonly'@'%';

GRANT SELECT ON pharma_counterfeit_db.v_manufacturer
TO 'role_readonly'@'%';

GRANT SELECT ON pharma_counterfeit_db.v_distributor
TO 'role_readonly'@'%';

GRANT SELECT ON pharma_counterfeit_db.v_retailer
TO 'role_readonly'@'%';

GRANT SELECT ON pharma_counterfeit_db.v_my_batches
TO 'role_readonly'@'%';

GRANT SELECT ON pharma_counterfeit_db.v_my_stock
TO 'role_readonly'@'%';
