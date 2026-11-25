
USE pharma_counterfeit_db;

-- evaluate rule-based detection against the injected counterfeit scenarios
-- run this script as an administrator because it reads injected_counterfeit

WITH scenario_rules AS (
    SELECT 'FAKE_MATERIAL' AS scenario_type, 'LOT_COA_NOT_VERIFIED' AS rule_code
    UNION ALL
    SELECT 'FAKE_MATERIAL', 'LOT_OVERWEIGHT'
    UNION ALL
    SELECT 'FAKE_MATERIAL', 'SUPPLIER_UNLICENSED'
    UNION ALL
    SELECT 'TRANSIT_SWAP', 'UNKNOWN_SERIAL'
    UNION ALL
    SELECT 'TRANSIT_SWAP', 'MISSING_PACK'
    UNION ALL
    SELECT 'INVENTED_SERIAL', 'UNKNOWN_SERIAL'
    UNION ALL
    SELECT 'CLONED_SERIAL', 'SOLD_TWICE'
    UNION ALL
    SELECT 'CLONED_SERIAL', 'CLONE_SCAN'
    UNION ALL
    SELECT 'UNLICENSED_HANDLER', 'HANDLER_UNLICENSED'
    UNION ALL
    SELECT 'STAGE_SKIPPED', 'STAGE_SKIPPED'
    UNION ALL
    SELECT 'RECORD_TAMPERED', 'HASH_MISMATCH'
),
scenario_list AS (
    SELECT DISTINCT scenario_type
    FROM scenario_rules
),
scenario_counts AS (
    SELECT
        sl.scenario_type,

        (
            SELECT COUNT(DISTINCT ic.inject_id)
            FROM injected_counterfeit ic
            WHERE ic.scenario_type = sl.scenario_type
        ) AS total_injected,

        (
            SELECT COUNT(DISTINCT ic.inject_id)
            FROM injected_counterfeit ic
            WHERE ic.scenario_type = sl.scenario_type
              AND EXISTS (
                  SELECT 1
                  FROM scenario_rules sr
                  JOIN anomaly_flag af
                    ON af.rule_code = sr.rule_code
                  WHERE sr.scenario_type = sl.scenario_type
                    AND (
                        (
                            sl.scenario_type = 'FAKE_MATERIAL'
                            AND ic.lot_id IS NOT NULL
                            AND af.lot_id = ic.lot_id
                        )
                        OR
                        (
                            sl.scenario_type <> 'FAKE_MATERIAL'
                            AND ic.serial_no IS NOT NULL
                            AND af.serial_no = ic.serial_no
                        )
                        OR
                        (
                            sl.scenario_type = 'RECORD_TAMPERED'
                            AND ic.event_id IS NOT NULL
                            AND af.event_id = ic.event_id
                        )
                    )
              )
        ) AS caught,

        (
            SELECT COUNT(DISTINCT af.flag_id)
            FROM scenario_rules sr
            JOIN anomaly_flag af
              ON af.rule_code = sr.rule_code
            WHERE sr.scenario_type = sl.scenario_type
              AND NOT EXISTS (
                  SELECT 1
                  FROM injected_counterfeit ic
                  WHERE
                      (
                          af.lot_id IS NOT NULL
                          AND ic.lot_id = af.lot_id
                      )
                      OR
                      (
                          af.serial_no IS NOT NULL
                          AND ic.serial_no = af.serial_no
                      )
                      OR
                      (
                          af.event_id IS NOT NULL
                          AND ic.event_id = af.event_id
                      )
              )
        ) AS false_alarms

    FROM scenario_list sl
)
SELECT
    scenario_type,
    total_injected,
    caught,
    total_injected - caught AS missed,
    false_alarms,
    ROUND(
        caught / NULLIF(caught + false_alarms, 0),
        4
    ) AS precision_score,
    ROUND(
        caught / NULLIF(total_injected, 0),
        4
    ) AS recall_score
FROM scenario_counts
ORDER BY scenario_type;


-- show rule-level findings that are not associated with a planted scenario
-- LOT_UNDERWEIGHT is intentional harmless noise in the seed data

SELECT
    rule_code,
    COUNT(*) AS total_flags,
    SUM(
        CASE
            WHEN NOT EXISTS (
                SELECT 1
                FROM injected_counterfeit ic
                WHERE
                    (anomaly_flag.lot_id IS NOT NULL
                     AND ic.lot_id = anomaly_flag.lot_id)
                    OR
                    (anomaly_flag.serial_no IS NOT NULL
                     AND ic.serial_no = anomaly_flag.serial_no)
                    OR
                    (anomaly_flag.event_id IS NOT NULL
                     AND ic.event_id = anomaly_flag.event_id)
            )
            THEN 1
            ELSE 0
        END
    ) AS flags_without_matching_injection
FROM anomaly_flag
WHERE rule_code IN (
    'LOT_UNDERWEIGHT',
    'MISSING_PACK'
)
GROUP BY rule_code
ORDER BY rule_code;
