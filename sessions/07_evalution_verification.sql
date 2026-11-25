
USE pharma_counterfeit_db;

-- check the number of injected records in each scenario
SELECT
    scenario_type,
    COUNT(*) AS injected_records
FROM injected_counterfeit
GROUP BY scenario_type
ORDER BY scenario_type;


-- check how many flags exist for each detection rule
SELECT
    rule_code,
    COUNT(*) AS total_flags
FROM anomaly_flag
GROUP BY rule_code
ORDER BY rule_code;


-- inspect fake material injections and their corresponding flags
SELECT
    ic.inject_id,
    ic.scenario_type,
    ic.lot_id,
    af.flag_id,
    af.rule_code,
    af.severity
FROM injected_counterfeit ic
LEFT JOIN anomaly_flag af
    ON af.lot_id = ic.lot_id
WHERE ic.scenario_type = 'FAKE_MATERIAL'
ORDER BY ic.inject_id;


-- inspect serial-based injections and their corresponding flags
SELECT
    ic.inject_id,
    ic.scenario_type,
    ic.serial_no,
    af.flag_id,
    af.rule_code,
    af.severity
FROM injected_counterfeit ic
LEFT JOIN anomaly_flag af
    ON af.serial_no = ic.serial_no
WHERE ic.scenario_type <> 'FAKE_MATERIAL'
ORDER BY ic.scenario_type, ic.inject_id;


-- inspect the number of flags that have no matching injected evidence
SELECT
    af.rule_code,
    COUNT(*) AS unmatched_flags
FROM anomaly_flag af
WHERE NOT EXISTS (
    SELECT 1
    FROM injected_counterfeit ic
    WHERE
        (af.lot_id IS NOT NULL AND ic.lot_id = af.lot_id)
        OR
        (af.serial_no IS NOT NULL AND ic.serial_no = af.serial_no)
        OR
        (af.event_id IS NOT NULL AND ic.event_id = af.event_id)
)
GROUP BY af.rule_code
ORDER BY af.rule_code;

-- inspect license history for the receivers of those missed records
SELECT
    ic.inject_id,
    ic.event_id,
    ic.serial_no,
    te.event_time,
    l.to_participant AS receiver_id,
    p.name AS receiver_name,
    lh.old_status,
    lh.new_status,
    lh.changed_at
FROM injected_counterfeit ic
JOIN trace_event te
    ON te.event_id = ic.event_id
JOIN shipment s
    ON s.shipment_id = te.shipment_id
JOIN link l
    ON l.link_id = s.link_id
JOIN participant p
    ON p.participant_id = l.to_participant
LEFT JOIN license_history lh
    ON lh.participant_id = p.participant_id
WHERE ic.scenario_type = 'UNLICENSED_HANDLER'
  AND NOT EXISTS (
      SELECT 1
      FROM anomaly_flag af
      WHERE af.rule_code = 'HANDLER_UNLICENSED'
        AND af.event_id = ic.event_id
  )
ORDER BY ic.inject_id, lh.changed_at
LIMIT 60;


-- summarize missed unlicensed-handler injections by receiver
SELECT
    l.to_participant AS receiver_id,
    p.name AS receiver_name,
    COUNT(*) AS missed_injections,
    MIN(te.event_time) AS first_event,
    MAX(te.event_time) AS last_event,
    MAX(ic.injected_at) AS latest_injection
FROM injected_counterfeit ic
JOIN trace_event te
    ON te.event_id = ic.event_id
JOIN shipment s
    ON s.shipment_id = te.shipment_id
JOIN link l
    ON l.link_id = s.link_id
JOIN participant p
    ON p.participant_id = l.to_participant
WHERE ic.scenario_type = 'UNLICENSED_HANDLER'
  AND NOT EXISTS (
      SELECT 1
      FROM anomaly_flag af
      WHERE af.rule_code = 'HANDLER_UNLICENSED'
        AND af.event_id = ic.event_id
  )
GROUP BY l.to_participant, p.name
ORDER BY missed_injections DESC;


-- inspect the event types and shipments of the incorrectly labelled injections
SELECT
    te.event_type,
    te.shipment_id,
    COUNT(*) AS record_count
FROM injected_counterfeit ic
JOIN trace_event te
    ON te.event_id = ic.event_id
WHERE ic.scenario_type = 'UNLICENSED_HANDLER'
  AND ic.event_id BETWEEN 251115 AND 251326
GROUP BY te.event_type, te.shipment_id
ORDER BY te.event_type, te.shipment_id;


-- inspect the shipment associated with the incorrectly labelled injections
SELECT
    s.shipment_id,
    s.link_id,
    s.ship_time,
    s.receive_time,
    s.status,
    l.from_participant,
    pf.name AS sender_name,
    l.to_participant,
    pt.name AS receiver_name,
    pt.license_status AS current_license_status
FROM shipment s
JOIN link l
    ON l.link_id = s.link_id
JOIN participant pf
    ON pf.participant_id = l.from_participant
JOIN participant pt
    ON pt.participant_id = l.to_participant
WHERE s.shipment_id = 33514;