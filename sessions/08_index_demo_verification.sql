
USE pharma_counterfeit_db;

-- 1. Verify the four indexes exist and are visible.
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

-- 2. Verify the sample serial has events.
SELECT
    serial_no,
    COUNT(*) AS event_count
FROM trace_event
WHERE serial_no = (
    SELECT serial_no
    FROM trace_event
    GROUP BY serial_no
    HAVING COUNT(*) >= 3
    ORDER BY serial_no
    LIMIT 1
)
GROUP BY serial_no;

-- 3. Verify the selected batch has packs.
SELECT
    batch_id,
    COUNT(*) AS pack_count
FROM pack
WHERE batch_id = (SELECT MIN(batch_id) FROM pack)
GROUP BY batch_id;

-- 4. Verify the selected link has shipments.
SELECT
    link_id,
    COUNT(*) AS shipment_count
FROM shipment
WHERE link_id = (SELECT MIN(link_id) FROM shipment)
GROUP BY link_id;
