
USE pharma_counterfeit_db;

DROP PROCEDURE IF EXISTS run_detection;

DELIMITER $$

CREATE PROCEDURE run_detection()
BEGIN

    -- rule 1: flag material lots without a verified certificate
    INSERT INTO anomaly_flag
        (rule_code, link_id, lot_id, severity, detected_at)
    SELECT
        'LOT_COA_NOT_VERIFIED',
        l.link_id,
        ml.lot_id,
        'HIGH',
        CONCAT(ml.received_date, ' 00:00:00')
    FROM material_lot ml
    LEFT JOIN link l
        ON l.from_participant = ml.supplier_id
       AND l.to_participant = ml.manufacturer_id
    WHERE ml.coa_verified = FALSE
      AND NOT EXISTS (
          SELECT 1
          FROM anomaly_flag af
          WHERE af.rule_code = 'LOT_COA_NOT_VERIFIED'
            AND af.lot_id = ml.lot_id
      );


    -- rule 2: flag material lots where received quantity exceeds sent quantity
    INSERT INTO anomaly_flag
        (rule_code, link_id, lot_id, severity, detected_at)
    SELECT
        'LOT_OVERWEIGHT',
        l.link_id,
        ml.lot_id,
        'HIGH',
        CONCAT(ml.received_date, ' 00:00:00')
    FROM material_lot ml
    LEFT JOIN link l
        ON l.from_participant = ml.supplier_id
       AND l.to_participant = ml.manufacturer_id
    WHERE ml.quantity_received_kg > ml.quantity_sent_kg
      AND NOT EXISTS (
          SELECT 1
          FROM anomaly_flag af
          WHERE af.rule_code = 'LOT_OVERWEIGHT'
            AND af.lot_id = ml.lot_id
      );


    -- rule 3: flag material lots where received quantity is below sent quantity
    INSERT INTO anomaly_flag
        (rule_code, link_id, lot_id, severity, detected_at)
    SELECT
        'LOT_UNDERWEIGHT',
        l.link_id,
        ml.lot_id,
        'LOW',
        CONCAT(ml.received_date, ' 00:00:00')
    FROM material_lot ml
    LEFT JOIN link l
        ON l.from_participant = ml.supplier_id
       AND l.to_participant = ml.manufacturer_id
    WHERE ml.quantity_received_kg < ml.quantity_sent_kg
      AND NOT EXISTS (
          SELECT 1
          FROM anomaly_flag af
          WHERE af.rule_code = 'LOT_UNDERWEIGHT'
            AND af.lot_id = ml.lot_id
      );


    -- rule 4: flag lots received while the supplier was not licensed
    INSERT INTO anomaly_flag
        (rule_code, link_id, lot_id, severity, detected_at)
    SELECT
        'SUPPLIER_UNLICENSED',
        l.link_id,
        ml.lot_id,
        'HIGH',
        CONCAT(ml.received_date, ' 00:00:00')
    FROM material_lot ml
    JOIN participant p
        ON p.participant_id = ml.supplier_id
    LEFT JOIN link l
        ON l.from_participant = ml.supplier_id
       AND l.to_participant = ml.manufacturer_id
    WHERE COALESCE(
        (
            SELECT lh.new_status
            FROM license_history lh
            WHERE lh.participant_id = ml.supplier_id
              AND lh.changed_at <= CONCAT(ml.received_date, ' 23:59:59')
            ORDER BY lh.changed_at DESC
            LIMIT 1
        ),
        (
            SELECT lh.old_status
            FROM license_history lh
            WHERE lh.participant_id = ml.supplier_id
              AND lh.changed_at > CONCAT(ml.received_date, ' 23:59:59')
            ORDER BY lh.changed_at ASC
            LIMIT 1
        ),
        p.license_status
    ) <> 'ACTIVE'
      AND NOT EXISTS (
          SELECT 1
          FROM anomaly_flag af
          WHERE af.rule_code = 'SUPPLIER_UNLICENSED'
            AND af.lot_id = ml.lot_id
      );


    -- rule 5: flag received events for serial numbers absent from the pack table
    INSERT INTO anomaly_flag
        (rule_code, serial_no, shipment_id, link_id, event_id,
         severity, detected_at)
    SELECT
        'UNKNOWN_SERIAL',
        te.serial_no,
        te.shipment_id,
        s.link_id,
        te.event_id,
        'CRITICAL',
        te.event_time
    FROM trace_event te
    JOIN shipment s
        ON s.shipment_id = te.shipment_id
    LEFT JOIN pack pk
        ON pk.serial_no = te.serial_no
    WHERE te.event_type = 'RECEIVED'
      AND pk.serial_no IS NULL
      AND NOT EXISTS (
          SELECT 1
          FROM anomaly_flag af
          WHERE af.rule_code = 'UNKNOWN_SERIAL'
            AND af.event_id = te.event_id
      );


    -- rule 6: flag dispatched packs that were not marked received
    INSERT INTO anomaly_flag
        (rule_code, serial_no, shipment_id, link_id, event_id,
         severity, detected_at)
    SELECT
        'MISSING_PACK',
        si.serial_no,
        s.shipment_id,
        s.link_id,
        te.event_id,
        'MEDIUM',
        s.receive_time
    FROM shipment_item si
    JOIN shipment s
        ON s.shipment_id = si.shipment_id
    LEFT JOIN trace_event te
        ON te.shipment_id = si.shipment_id
       AND te.serial_no = si.serial_no
       AND te.event_type = 'DISPATCHED'
    WHERE si.received = FALSE
      AND s.receive_time IS NOT NULL
      AND NOT EXISTS (
          SELECT 1
          FROM anomaly_flag af
          WHERE af.rule_code = 'MISSING_PACK'
            AND af.shipment_id = si.shipment_id
            AND af.serial_no = si.serial_no
      );


    -- rule 7: flag every SOLD event that has an earlier SOLD event for the same serial
    INSERT INTO anomaly_flag
        (rule_code, serial_no, shipment_id, link_id, event_id,
         severity, detected_at)
    SELECT
        'SOLD_TWICE',
        later_event.serial_no,
        later_event.shipment_id,
        s.link_id,
        later_event.event_id,
        'CRITICAL',
        later_event.event_time
    FROM trace_event later_event
    JOIN shipment s
        ON s.shipment_id = later_event.shipment_id
    WHERE later_event.event_type = 'SOLD'
      AND EXISTS (
          SELECT 1
          FROM trace_event earlier_event
          WHERE earlier_event.serial_no = later_event.serial_no
            AND earlier_event.event_type = 'SOLD'
            AND earlier_event.event_time < later_event.event_time
      )
      AND NOT EXISTS (
          SELECT 1
          FROM anomaly_flag af
          WHERE af.rule_code = 'SOLD_TWICE'
            AND af.event_id = later_event.event_id
      );


    -- rule 8: flag packs received by handlers whose license was not active
    INSERT INTO anomaly_flag
        (rule_code, serial_no, shipment_id, link_id, event_id,
         severity, detected_at)
    SELECT
        'HANDLER_UNLICENSED',
        te.serial_no,
        te.shipment_id,
        s.link_id,
        te.event_id,
        'HIGH',
        te.event_time
    FROM trace_event te
    JOIN shipment s
        ON s.shipment_id = te.shipment_id
    JOIN link l
        ON l.link_id = s.link_id
    JOIN participant p
        ON p.participant_id = l.to_participant
    WHERE te.event_type = 'RECEIVED'
      AND COALESCE(
          (
              SELECT lh.new_status
              FROM license_history lh
              WHERE lh.participant_id = l.to_participant
                AND lh.changed_at <= te.event_time
              ORDER BY lh.changed_at DESC
              LIMIT 1
          ),
          (
              SELECT lh.old_status
              FROM license_history lh
              WHERE lh.participant_id = l.to_participant
                AND lh.changed_at > te.event_time
              ORDER BY lh.changed_at ASC
              LIMIT 1
          ),
          p.license_status
      ) <> 'ACTIVE'
      AND NOT EXISTS (
          SELECT 1
          FROM anomaly_flag af
          WHERE af.rule_code = 'HANDLER_UNLICENSED'
            AND af.event_id = te.event_id
      );


    -- rule 9: flag packs dispatched by a participant who never received them
    INSERT INTO anomaly_flag
        (rule_code, serial_no, shipment_id, link_id, event_id,
         severity, detected_at)
    SELECT
        'STAGE_SKIPPED',
        te.serial_no,
        te.shipment_id,
        s.link_id,
        te.event_id,
        'HIGH',
        te.event_time
    FROM trace_event te
    JOIN shipment s
        ON s.shipment_id = te.shipment_id
    JOIN link current_link
        ON current_link.link_id = s.link_id
    JOIN pack pk
        ON pk.serial_no = te.serial_no
    JOIN batch b
        ON b.batch_id = pk.batch_id
    WHERE te.event_type = 'DISPATCHED'
      AND current_link.from_participant <> b.manufacturer_id
      AND NOT EXISTS (
          SELECT 1
          FROM trace_event previous_event
          JOIN shipment previous_shipment
              ON previous_shipment.shipment_id = previous_event.shipment_id
          JOIN link previous_link
              ON previous_link.link_id = previous_shipment.link_id
          WHERE previous_event.serial_no = te.serial_no
            AND previous_event.event_type = 'RECEIVED'
            AND previous_link.to_participant = current_link.from_participant
            AND previous_event.event_time < te.event_time
      )
      AND NOT EXISTS (
          SELECT 1
          FROM anomaly_flag af
          WHERE af.rule_code = 'STAGE_SKIPPED'
            AND af.event_id = te.event_id
      );

END$$

DELIMITER ;
