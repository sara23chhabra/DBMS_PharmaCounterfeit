-- grant the existing project roles access to the isolated test database
-- does not create roles or modify grants on pharma_counterfeit_db

-- create the independent database roles

-- give the admin full privileges on this project database
GRANT ALL PRIVILEGES
ON pharma_counterfeit_test.*
TO 'role_admin'@'%';

-- allow detection to read all real project tables
GRANT SELECT ON pharma_counterfeit_test.participant
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_test.license_history
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_test.drug
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_test.material_lot
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_test.batch
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_test.batch_material
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_test.pack
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_test.link
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_test.shipment
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_test.shipment_item
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_test.trace_event
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_test.anomaly_flag
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_test.link_risk_score
TO 'role_detection'@'%';

GRANT SELECT ON pharma_counterfeit_test.risk_factor
TO 'role_detection'@'%';

-- allow detection to insert anomaly flags
GRANT INSERT ON pharma_counterfeit_test.anomaly_flag
TO 'role_detection'@'%';

-- allow the ledger role to read real project tables
GRANT SELECT ON pharma_counterfeit_test.participant
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_test.license_history
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_test.drug
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_test.material_lot
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_test.batch
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_test.batch_material
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_test.pack
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_test.link
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_test.shipment
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_test.shipment_item
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_test.trace_event
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_test.anomaly_flag
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_test.link_risk_score
TO 'role_ledger'@'%';

GRANT SELECT ON pharma_counterfeit_test.risk_factor
TO 'role_ledger'@'%';

-- allow the ledger role to update only the ledger_synced column
GRANT UPDATE (ledger_synced)
ON pharma_counterfeit_test.material_lot
TO 'role_ledger'@'%';

GRANT UPDATE (ledger_synced)
ON pharma_counterfeit_test.batch
TO 'role_ledger'@'%';

GRANT UPDATE (ledger_synced)
ON pharma_counterfeit_test.trace_event
TO 'role_ledger'@'%';

-- allow read-only access to project views
GRANT SELECT ON pharma_counterfeit_test.v_link
TO 'role_readonly'@'%';

GRANT SELECT ON pharma_counterfeit_test.v_serial_journey
TO 'role_readonly'@'%';

GRANT SELECT ON pharma_counterfeit_test.v_link_stats
TO 'role_readonly'@'%';

GRANT SELECT ON pharma_counterfeit_test.v_open_flags
TO 'role_readonly'@'%';

GRANT SELECT ON pharma_counterfeit_test.v_supplier
TO 'role_readonly'@'%';

GRANT SELECT ON pharma_counterfeit_test.v_manufacturer
TO 'role_readonly'@'%';

GRANT SELECT ON pharma_counterfeit_test.v_distributor
TO 'role_readonly'@'%';

GRANT SELECT ON pharma_counterfeit_test.v_retailer
TO 'role_readonly'@'%';

GRANT SELECT ON pharma_counterfeit_test.v_my_batches
TO 'role_readonly'@'%';

GRANT SELECT ON pharma_counterfeit_test.v_my_stock
TO 'role_readonly'@'%';


-- create the application role

-- allow reading and inserting into real project tables
GRANT SELECT, INSERT ON pharma_counterfeit_test.participant
TO 'role_app'@'%';

GRANT SELECT, INSERT ON pharma_counterfeit_test.license_history
TO 'role_app'@'%';

GRANT SELECT, INSERT ON pharma_counterfeit_test.drug
TO 'role_app'@'%';

GRANT SELECT, INSERT ON pharma_counterfeit_test.material_lot
TO 'role_app'@'%';

GRANT SELECT, INSERT ON pharma_counterfeit_test.batch
TO 'role_app'@'%';

GRANT SELECT, INSERT ON pharma_counterfeit_test.batch_material
TO 'role_app'@'%';

GRANT SELECT, INSERT ON pharma_counterfeit_test.pack
TO 'role_app'@'%';

GRANT SELECT, INSERT ON pharma_counterfeit_test.link
TO 'role_app'@'%';

GRANT SELECT, INSERT ON pharma_counterfeit_test.shipment
TO 'role_app'@'%';

GRANT SELECT, INSERT ON pharma_counterfeit_test.shipment_item
TO 'role_app'@'%';

GRANT SELECT, INSERT ON pharma_counterfeit_test.trace_event
TO 'role_app'@'%';

GRANT SELECT, INSERT ON pharma_counterfeit_test.anomaly_flag
TO 'role_app'@'%';

GRANT SELECT, INSERT ON pharma_counterfeit_test.link_risk_score
TO 'role_app'@'%';

GRANT SELECT, INSERT ON pharma_counterfeit_test.risk_factor
TO 'role_app'@'%';

-- allow execution of application procedures
GRANT EXECUTE ON PROCEDURE pharma_counterfeit_test.create_batch
TO 'role_app'@'%';

GRANT EXECUTE ON PROCEDURE pharma_counterfeit_test.approve_batch
TO 'role_app'@'%';

GRANT EXECUTE ON PROCEDURE pharma_counterfeit_test.generate_packs
TO 'role_app'@'%';

GRANT EXECUTE ON PROCEDURE pharma_counterfeit_test.dispatch_shipment
TO 'role_app'@'%';

GRANT EXECUTE ON PROCEDURE pharma_counterfeit_test.receive_shipment
TO 'role_app'@'%';

GRANT EXECUTE ON PROCEDURE pharma_counterfeit_test.sell_pack
TO 'role_app'@'%';

GRANT EXECUTE ON PROCEDURE pharma_counterfeit_test.recall_batch
TO 'role_app'@'%';


-- create manufacturer and retailer roles

-- manufacturer can view only their own batches and stock
GRANT SELECT ON pharma_counterfeit_test.v_my_batches
TO 'role_manufacturer'@'%';

GRANT SELECT ON pharma_counterfeit_test.v_my_stock
TO 'role_manufacturer'@'%';

-- manufacturer can execute only manufacturer operations
GRANT EXECUTE ON PROCEDURE pharma_counterfeit_test.create_batch
TO 'role_manufacturer'@'%';

GRANT EXECUTE ON PROCEDURE pharma_counterfeit_test.generate_packs
TO 'role_manufacturer'@'%';

GRANT EXECUTE ON PROCEDURE pharma_counterfeit_test.dispatch_shipment
TO 'role_manufacturer'@'%';

-- retailer can view only their own stock
GRANT SELECT ON pharma_counterfeit_test.v_my_stock
TO 'role_retailer'@'%';

-- retailer can execute only retailer operations
GRANT EXECUTE ON PROCEDURE pharma_counterfeit_test.receive_shipment
TO 'role_retailer'@'%';

GRANT EXECUTE ON PROCEDURE pharma_counterfeit_test.sell_pack
TO 'role_retailer'@'%';
