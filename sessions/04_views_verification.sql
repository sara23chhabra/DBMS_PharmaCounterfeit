-- Whether the view was created
SHOW FULL TABLES
WHERE Table_type = 'VIEW';

-- Whether the view returns the expected columns and data
SELECT *
FROM v_serial_journey
ORDER BY serial_no, event_time, event_id;

-- Whether manufactured events correctly show the manufacturer
SELECT *
FROM v_serial_journey
WHERE event_type = 'MANUFACTURED'
ORDER BY event_time;

-- Whether unknown serial events are retained
SELECT
    COUNT(*) AS unknown_serial_events
FROM v_serial_journey j
WHERE NOT EXISTS (
    SELECT 1
    FROM pack p
    WHERE p.serial_no = j.serial_no
);

SELECT *
FROM v_link_stats
ORDER BY link_id;

SELECT
    COUNT(*) AS total_links,
    SUM(total_shipments) AS total_shipments,
    SUM(total_packs) AS total_packs,
    SUM(partial_shipments) AS partial_shipments,
    SUM(open_flags) AS open_flags,
    MAX(mismatch_rate) AS highest_mismatch_rate
FROM v_link_stats;

-- Displays all currently unresolved anomaly flags with their associated supply-chain details.
SELECT *
FROM v_open_flags
ORDER BY detected_at DESC, flag_id DESC;

-- Counts how many unresolved anomaly flags are currently present.
SELECT COUNT(*) AS unresolved_flags
FROM v_open_flags;

-- Counts participants belonging to each supply-chain category.
SELECT
    participant_type,
    COUNT(*) AS participant_count
FROM participant
GROUP BY participant_type;

-- Checks whether each participant view returns the correct category.
SELECT 'SUPPLIER' AS view_type, COUNT(*) AS total
FROM v_supplier

UNION ALL

SELECT 'MANUFACTURER', COUNT(*)
FROM v_manufacturer

UNION ALL

SELECT 'DISTRIBUTOR', COUNT(*)
FROM v_distributor

UNION ALL

SELECT 'RETAILER', COUNT(*)
FROM v_retailer;

-- Checks whether both user-specific views were created.
SHOW FULL TABLES
WHERE Table_type = 'VIEW'
  AND Tables_in_pharma_counterfeit_db IN (
      'v_my_batches',
      'v_my_stock'
  );

-- Displays your current MySQL username and the participant ID extracted from it.
SELECT
    USER() AS current_mysql_user,
    CAST(
        SUBSTRING_INDEX(
            SUBSTRING_INDEX(USER(), '@', 1),
            '_',
            -1
        ) AS UNSIGNED
    ) AS extracted_participant_id;