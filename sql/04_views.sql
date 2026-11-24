-- v_serial_journey
USE pharma_counterfeit_db;

CREATE OR REPLACE VIEW v_serial_journey AS
SELECT
    te.serial_no,
    te.event_id,
    te.event_type,
    te.event_time,
    te.shipment_id,

    COALESCE(
        sender.name,
        CASE
            WHEN te.event_type = 'MANUFACTURED' THEN manufacturer.name
            WHEN te.event_type = 'RECALLED' THEN holder.name
        END
    ) AS sender_name,

    COALESCE(
        sender.city,
        CASE
            WHEN te.event_type = 'MANUFACTURED' THEN manufacturer.city
            WHEN te.event_type = 'RECALLED' THEN holder.city
        END
    ) AS sender_city,

    COALESCE(
        receiver.name,
        CASE
            WHEN te.event_type = 'MANUFACTURED' THEN manufacturer.name
            WHEN te.event_type = 'RECALLED' THEN holder.name
        END
    ) AS receiver_name,

    COALESCE(
        receiver.city,
        CASE
            WHEN te.event_type = 'MANUFACTURED' THEN manufacturer.city
            WHEN te.event_type = 'RECALLED' THEN holder.city
        END
    ) AS receiver_city

FROM trace_event te

LEFT JOIN shipment s
    ON te.shipment_id = s.shipment_id

LEFT JOIN link l
    ON s.link_id = l.link_id

LEFT JOIN participant sender
    ON l.from_participant = sender.participant_id

LEFT JOIN participant receiver
    ON l.to_participant = receiver.participant_id

LEFT JOIN pack pk
    ON te.serial_no = pk.serial_no

LEFT JOIN batch b
    ON pk.batch_id = b.batch_id

LEFT JOIN participant manufacturer
    ON b.manufacturer_id = manufacturer.participant_id

LEFT JOIN participant holder
    ON pk.current_owner = holder.participant_id;

-- v_link_stats
CREATE OR REPLACE VIEW v_link_stats AS

WITH shipment_stats AS (
    SELECT
        link_id,
        COUNT(*) AS total_shipments,
        SUM(status = 'PARTIAL') AS partial_shipments
    FROM shipment
    GROUP BY link_id
),

pack_stats AS (
    SELECT
        s.link_id,

        COUNT(si.serial_no) AS total_packs,

        SUM(
            CASE
                WHEN s.status IN ('RECEIVED', 'PARTIAL')
                     AND si.received = FALSE
                THEN 1
                ELSE 0
            END
        ) AS missing_packs,

        SUM(
            CASE
                WHEN s.status IN ('RECEIVED', 'PARTIAL')
                THEN 1
                ELSE 0
            END
        ) AS completed_packs

    FROM shipment s
    JOIN shipment_item si
        ON s.shipment_id = si.shipment_id
    GROUP BY s.link_id
),

flag_stats AS (
    SELECT
        link_id,
        COUNT(*) AS open_flags
    FROM anomaly_flag
    WHERE resolved = FALSE
      AND link_id IS NOT NULL
    GROUP BY link_id
)

SELECT
    vl.link_id,
    vl.link_type AS stage,

    COALESCE(ss.total_shipments, 0) AS total_shipments,
    COALESCE(ps.total_packs, 0) AS total_packs,
    COALESCE(ss.partial_shipments, 0) AS partial_shipments,

    CASE
        WHEN COALESCE(ps.completed_packs, 0) = 0 THEN 0
        ELSE ROUND(
            100.0 * ps.missing_packs / ps.completed_packs,
            2
        )
    END AS mismatch_rate,

    COALESCE(fs.open_flags, 0) AS open_flags

FROM v_link vl

LEFT JOIN shipment_stats ss
    ON vl.link_id = ss.link_id

LEFT JOIN pack_stats ps
    ON vl.link_id = ps.link_id

LEFT JOIN flag_stats fs
    ON vl.link_id = fs.link_id;

-- v_open_flags

CREATE OR REPLACE VIEW v_open_flags AS

SELECT
    af.flag_id,
    af.rule_code,
    af.serial_no,
    af.shipment_id,
    af.link_id,
    af.event_id,
    af.lot_id,
    af.severity,
    af.detected_at,
    vl.link_type AS stage,
    sender.name AS sender_name,
    receiver.name AS receiver_name

FROM anomaly_flag af

LEFT JOIN v_link vl
    ON af.link_id = vl.link_id

LEFT JOIN participant sender
    ON vl.from_participant = sender.participant_id

LEFT JOIN participant receiver
    ON vl.to_participant = receiver.participant_id

WHERE af.resolved = FALSE;

-- participant views
CREATE OR REPLACE VIEW v_supplier AS
SELECT *
FROM participant
WHERE participant_type = 'SUPPLIER';


CREATE OR REPLACE VIEW v_manufacturer AS
SELECT *
FROM participant
WHERE participant_type = 'MANUFACTURER';


CREATE OR REPLACE VIEW v_distributor AS
SELECT *
FROM participant
WHERE participant_type = 'DISTRIBUTOR';


CREATE OR REPLACE VIEW v_retailer AS
SELECT *
FROM participant
WHERE participant_type = 'RETAILER';

-- user specific views

CREATE OR REPLACE VIEW v_my_batches AS

SELECT *
FROM batch
WHERE manufacturer_id =
    CAST(
        SUBSTRING_INDEX(
            SUBSTRING_INDEX(USER(), '@', 1),
            '_',
            -1
        ) AS UNSIGNED
    );


CREATE OR REPLACE VIEW v_my_stock AS

SELECT *
FROM pack
WHERE current_owner =
    CAST(
        SUBSTRING_INDEX(
            SUBSTRING_INDEX(USER(), '@', 1),
            '_',
            -1
        ) AS UNSIGNED
    );
