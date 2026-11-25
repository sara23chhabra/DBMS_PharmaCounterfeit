
USE pharma_counterfeit_db;

-- Use normal optimizer behavior: invisible indexes are ignored.
SET SESSION optimizer_switch = 'use_invisible_indexes=off';

-- Select representative values from the existing seed data.
SELECT serial_no
INTO @demo_serial
FROM trace_event
GROUP BY serial_no
HAVING COUNT(*) >= 3
ORDER BY serial_no
LIMIT 1;

SELECT MIN(batch_id)
INTO @demo_batch
FROM pack;

SELECT MIN(link_id)
INTO @demo_link
FROM shipment;

-- 1. SERIAL JOURNEY: compare the serial_no, event_time index.

SELECT '1. SERIAL JOURNEY - INDEX INVISIBLE' AS test;
ALTER TABLE trace_event
ALTER INDEX idx_trace_event_serial_time INVISIBLE;

EXPLAIN ANALYZE
SELECT event_id, serial_no, event_type, event_time, shipment_id
FROM trace_event
WHERE serial_no = @demo_serial
ORDER BY event_time, event_id;

ALTER TABLE trace_event
ALTER INDEX idx_trace_event_serial_time VISIBLE;

SELECT '1. SERIAL JOURNEY - INDEX VISIBLE' AS test;

EXPLAIN ANALYZE
SELECT event_id, serial_no, event_type, event_time, shipment_id
FROM trace_event
WHERE serial_no = @demo_serial
ORDER BY event_time, event_id;


-- 2. EVENTS IN A WEEK: compare the event_time index.

SELECT '2. EVENTS IN A WEEK - INDEX INVISIBLE' AS test;
ALTER TABLE trace_event
ALTER INDEX idx_trace_event_time INVISIBLE;

EXPLAIN ANALYZE
SELECT event_id, serial_no, event_type, event_time
FROM trace_event
WHERE event_time >= '2026-09-07 00:00:00'
  AND event_time <  '2026-09-14 00:00:00';

ALTER TABLE trace_event
ALTER INDEX idx_trace_event_time VISIBLE;

SELECT '2. EVENTS IN A WEEK - INDEX VISIBLE' AS test;

EXPLAIN ANALYZE
SELECT event_id, serial_no, event_type, event_time
FROM trace_event
WHERE event_time >= '2026-09-07 00:00:00'
  AND event_time <  '2026-09-14 00:00:00';


-- 3. BATCH PACKS: compare the batch_id index.

SELECT '3. BATCH PACKS - INDEX INVISIBLE' AS test;
ALTER TABLE pack
ALTER INDEX idx_pack_batch INVISIBLE;

EXPLAIN ANALYZE
SELECT serial_no, batch_id, current_owner, status
FROM pack
WHERE batch_id = @demo_batch;

ALTER TABLE pack
ALTER INDEX idx_pack_batch VISIBLE;

SELECT '3. BATCH PACKS - INDEX VISIBLE' AS test;

EXPLAIN ANALYZE
SELECT serial_no, batch_id, current_owner, status
FROM pack
WHERE batch_id = @demo_batch;


-- 4. LINK SHIPMENTS: compare the link_id, ship_time index.

SELECT '4. LINK SHIPMENTS - INDEX INVISIBLE' AS test;
ALTER TABLE shipment
ALTER INDEX idx_shipment_link_time INVISIBLE;

EXPLAIN ANALYZE
SELECT shipment_id, link_id, ship_time, receive_time, status
FROM shipment
WHERE link_id = @demo_link
ORDER BY ship_time;

ALTER TABLE shipment
ALTER INDEX idx_shipment_link_time VISIBLE;

SELECT '4. LINK SHIPMENTS - INDEX VISIBLE' AS test;

EXPLAIN ANALYZE
SELECT shipment_id, link_id, ship_time, receive_time, status
FROM shipment
WHERE link_id = @demo_link
ORDER BY ship_time;


-- Confirm that all four indexes have been restored to visible.
SELECT
    TABLE_NAME,
    INDEX_NAME,
    IS_VISIBLE
FROM information_schema.statistics
WHERE TABLE_SCHEMA = 'pharma_counterfeit_db'
  AND INDEX_NAME IN (
      'idx_trace_event_serial_time',
      'idx_trace_event_time',
      'idx_pack_batch',
      'idx_shipment_link_time'
  )
GROUP BY TABLE_NAME, INDEX_NAME, IS_VISIBLE
ORDER BY TABLE_NAME, INDEX_NAME;
