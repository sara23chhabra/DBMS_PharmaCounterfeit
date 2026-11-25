
import argparse
import json
import math
from datetime import date, datetime, timezone

from common.config import get_mysql, get_mongo_db
from common.hashing import GENESIS_HASH, block_hash, event_hash


def to_datetime(value):
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())

    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed

    return None


def haversine_km(lat1, lon1, lat2, lon2):
    radius = 6371.0

    lat1 = math.radians(float(lat1))
    lon1 = math.radians(float(lon1))
    lat2 = math.radians(float(lat2))
    lon2 = math.radians(float(lon2))

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    return 2 * radius * math.asin(math.sqrt(a))


def get_pack_details(cursor, serial_no):
    query = """
        SELECT
            p.serial_no,
            p.batch_id,
            p.current_owner,
            p.status,
            b.batch_no,
            b.expiry_date,
            b.qc_status,
            b.manufacturer_id,
            d.gtin
        FROM pack p
        JOIN batch b
            ON b.batch_id = p.batch_id
        JOIN drug d
            ON d.drug_id = b.drug_id
        WHERE p.serial_no = %s
    """

    cursor.execute(query, (serial_no,))
    return cursor.fetchone()


def get_sql_events(cursor, serial_no):
    query = """
        SELECT
            e.event_id,
            e.serial_no,
            e.event_type,
            e.shipment_id,
            e.event_time,
            e.event_hash,
            CASE
                WHEN e.event_type = 'RECALLED'
                    THEN p.current_owner
                WHEN e.shipment_id IS NOT NULL
                    THEN l.from_participant
                ELSE b.manufacturer_id
            END AS from_id,
            CASE
                WHEN e.event_type = 'RECALLED'
                    THEN p.current_owner
                WHEN e.shipment_id IS NOT NULL
                    THEN l.to_participant
                ELSE b.manufacturer_id
            END AS to_id
        FROM trace_event e
        LEFT JOIN shipment s
            ON s.shipment_id = e.shipment_id
        LEFT JOIN link l
            ON l.link_id = s.link_id
        LEFT JOIN pack p
            ON p.serial_no = e.serial_no
        LEFT JOIN batch b
            ON b.batch_id = p.batch_id
        WHERE e.serial_no = %s
        ORDER BY e.event_time, e.event_id
    """

    cursor.execute(query, (serial_no,))
    return cursor.fetchall()


def get_ledger_blocks(mongo_db):
    return list(
        mongo_db["ledger_blocks"].find(
            {},
            {"_id": 0},
        ).sort("block_index", 1)
    )


def check_block_chain(blocks):
    reasons = []
    expected_index = 0
    previous_hash = GENESIS_HASH

    for block in blocks:
        block_index = block.get("block_index")

        if block_index != expected_index:
            reasons.append(
                f"Unexpected block index: expected {expected_index}, "
                f"found {block_index}."
            )

        if block.get("prev_block_hash") != previous_hash:
            reasons.append(
                f"Previous hash mismatch at block {block_index}."
            )

        item_hashes = [
            item.get("hash", "")
            for item in block.get("items", [])
        ]

        calculated_hash = block_hash(
            block_index,
            block.get("timestamp"),
            block.get("block_type"),
            item_hashes,
            block.get("prev_block_hash"),
        )

        if calculated_hash != block.get("block_hash"):
            reasons.append(
                f"Block hash mismatch at block {block_index}."
            )

        previous_hash = block.get("block_hash")
        expected_index += 1

    return reasons


def get_ledger_event_items(blocks):
    event_items = {}

    for block in blocks:
        for item in block.get("items", []):
            if item.get("kind") == "event":
                event_items.setdefault(item.get("id"), []).append(item)

    return event_items


def check_production_registration(serial_no, blocks):
    for block in blocks:
        if block.get("block_type") != "PRODUCTION":
            continue

        for item in block.get("items", []):
            if (
                item.get("kind") == "event"
                and item.get("serial_no") == serial_no
                and item.get("event_type") == "MANUFACTURED"
            ):
                return True

    return False


def check_event_hashes(sql_events, ledger_event_items):
    reasons = []

    for event in sql_events:
        calculated_hash = event_hash(
            event["event_id"],
            event["serial_no"],
            event["event_type"],
            event["from_id"],
            event["to_id"],
            event["shipment_id"],
            event["event_time"],
        )

        if calculated_hash != event["event_hash"]:
            reasons.append(
                f"SQL event hash mismatch for event {event['event_id']}."
            )

        matching_items = ledger_event_items.get(event["event_id"], [])

        if not matching_items:
            reasons.append(
                f"Event {event['event_id']} is missing from the ledger."
            )
            continue

        if not any(
            item.get("hash") == event["event_hash"]
            for item in matching_items
        ):
            reasons.append(
                f"Ledger event hash mismatch for event {event['event_id']}."
            )

    return reasons


def get_license_status_at(cursor, participant_id, event_time):
    query = """
        SELECT
            license_status,
            license_issue_date,
            license_valid_till
        FROM participant
        WHERE participant_id = %s
    """

    cursor.execute(query, (participant_id,))
    participant = cursor.fetchone()

    if participant is None:
        return None

    current_status = participant["license_status"]

    if current_status is None:
        return None

    history_query = """
        SELECT
            old_status,
            new_status,
            changed_at
        FROM license_history
        WHERE participant_id = %s
        ORDER BY changed_at DESC, history_id DESC
    """

    cursor.execute(history_query, (participant_id,))
    history = cursor.fetchall()

    status_at_event = current_status

    for change in history:
        changed_at = to_datetime(change["changed_at"])

        if changed_at and changed_at > event_time:
            status_at_event = change["old_status"]
        else:
            break

    issue_date = participant["license_issue_date"]
    valid_till = participant["license_valid_till"]

    if issue_date and event_time.date() < issue_date:
        return "NOT_YET_ISSUED"

    if valid_till and event_time.date() > valid_till:
        return "EXPIRED"

    return status_at_event


def check_handler_license(cursor, participant_id, event_time, event_id):
    if participant_id is None:
        return [
            f"Could not identify the handler for event {event_id}."
        ]

    status = get_license_status_at(
        cursor,
        participant_id,
        event_time,
    )

    if status != "ACTIVE":
        return [
            f"Participant {participant_id} had license status "
            f"{status} at event {event_id}."
        ]

    return []


def check_continuity(cursor, sql_events):
    reasons = []
    current_holder = None
    pending_shipment = None

    for event in sql_events:
        event_type = event["event_type"]
        event_time = to_datetime(event["event_time"])
        event_id = event["event_id"]

        if event_type == "MANUFACTURED":
            current_holder = event["to_id"]
            continue

        if event_type == "DISPATCHED":
            if pending_shipment is not None:
                reasons.append(
                    f"Shipment {pending_shipment} was dispatched "
                    "without completing the previous handover."
                )

            sender_id = event["from_id"]

            if current_holder is None:
                reasons.append(
                    f"No manufacturer or previous holder found "
                    f"before event {event_id}."
                )
            elif sender_id != current_holder:
                reasons.append(
                    f"Stage skipped or incorrect sender at event "
                    f"{event_id}: expected participant "
                    f"{current_holder}, found {sender_id}."
                )

            reasons.extend(
                check_handler_license(
                    cursor,
                    sender_id,
                    event_time,
                    event_id,
                )
            )

            pending_shipment = event["shipment_id"]
            continue

        if event_type == "RECEIVED":
            sender_id = event["from_id"]
            receiver_id = event["to_id"]

            if pending_shipment != event["shipment_id"]:
                reasons.append(
                    f"RECEIVED event {event_id} has no matching "
                    "preceding DISPATCHED event."
                )

            if current_holder is not None and sender_id != current_holder:
                reasons.append(
                    f"Incorrect sender at RECEIVED event {event_id}."
                )

            reasons.extend(
                check_handler_license(
                    cursor,
                    receiver_id,
                    event_time,
                    event_id,
                )
            )

            current_holder = receiver_id
            pending_shipment = None
            continue

        if event_type == "SOLD":
            sender_id = event["from_id"]

            if current_holder is not None and sender_id != current_holder:
                reasons.append(
                    f"Pack was sold by an unexpected participant "
                    f"at event {event_id}."
                )

            reasons.extend(
                check_handler_license(
                    cursor,
                    sender_id,
                    event_time,
                    event_id,
                )
            )

            continue

        if event_type == "RECALLED":
            continue

    if pending_shipment is not None:
        reasons.append(
            f"Shipment {pending_shipment} has no matching RECEIVED event."
        )

    return reasons


def check_scan_history(
    mongo_db,
    serial_no,
    current_scan_time,
    current_lat=None,
    current_lon=None,
):
    reasons = []
    collection = mongo_db["scan_logs"]

    previous_scans = list(
        collection.find(
            {"serial_no": serial_no}
        ).sort("scanned_at", 1)
    )

    total_scans = len(previous_scans) + 1

    if total_scans > 3:
        reasons.append(
            f"Serial will have been scanned more than 3 times "
            f"including this scan ({total_scans} scans)."
        )

    scans_to_compare = []

    for scan in previous_scans:
        scans_to_compare.append({
            "scanned_at": to_datetime(scan.get("scanned_at")),
            "lat": scan.get("lat"),
            "lon": scan.get("lon"),
        })

    scans_to_compare.append({
        "scanned_at": to_datetime(current_scan_time),
        "lat": current_lat,
        "lon": current_lon,
    })

    for i, first in enumerate(scans_to_compare):
        first_time = first["scanned_at"]
        first_lat = first["lat"]
        first_lon = first["lon"]

        if (
            first_time is None
            or first_lat is None
            or first_lon is None
        ):
            continue

        for second in scans_to_compare[i + 1:]:
            second_time = second["scanned_at"]
            second_lat = second["lat"]
            second_lon = second["lon"]

            if (
                second_time is None
                or second_lat is None
                or second_lon is None
            ):
                continue

            days_apart = abs(
                (second_time - first_time).total_seconds()
            ) / 86400

            if days_apart <= 7:
                distance = haversine_km(
                    first_lat,
                    first_lon,
                    second_lat,
                    second_lon,
                )

                if distance > 300:
                    reasons.append(
                        "Two scans were recorded more than 300 km "
                        "apart within 7 days."
                    )
                    return reasons

    return reasons


def check_previous_sale(sql_events):
    for event in sql_events:
        if event["event_type"] == "SOLD":
            return [
                "This serial has a previous SOLD event."
            ]

    return []


def get_route(cursor, serial_no):
    query = """
        SELECT *
        FROM v_serial_journey
        WHERE serial_no = %s
        ORDER BY event_time, event_id
    """

    cursor.execute(query, (serial_no,))
    return cursor.fetchall()


def save_scan(
    mongo_db,
    serial_no,
    verdict,
    reasons,
    scan_time,
    city=None,
    lat=None,
    lon=None,
):
    scan_document = {
        "serial_no": serial_no,
        "scanned_at": scan_time,
        "city": city,
        "lat": lat,
        "lon": lon,
        "verdict": verdict,
        "reasons": reasons,
    }

    mongo_db["scan_logs"].insert_one(scan_document)


def verify(
    serial_no,
    qr_gtin=None,
    qr_batch_no=None,
    qr_expiry=None,
    city=None,
    lat=None,
    lon=None,
):
    connection = get_mysql()
    mongo_db = get_mongo_db()
    cursor = None
    current_scan_time = datetime.now(timezone.utc)

    try:
        cursor = connection.cursor(dictionary=True)

        pack = get_pack_details(cursor, serial_no)

        if pack is None:
            verdict = "FAKE"
            reasons = [
                "Serial number is not registered in the pack table."
            ]

            save_scan(
                mongo_db,
                serial_no,
                verdict,
                reasons,
                current_scan_time,
                city,
                lat,
                lon,
            )

            return {
                "serial_no": serial_no,
                "verdict": verdict,
                "reasons": reasons,
                "route": [],
            }

        reasons = []

        if qr_gtin is not None and qr_gtin != pack["gtin"]:
            reasons.append("QR GTIN does not match the database.")

        if qr_batch_no is not None and qr_batch_no != pack["batch_no"]:
            reasons.append("QR batch number does not match the database.")

        if qr_expiry is not None:
            database_expiry = pack["expiry_date"].isoformat()

            if qr_expiry != database_expiry:
                reasons.append(
                    "QR expiry date does not match the database."
                )

        blocks = get_ledger_blocks(mongo_db)
        ledger_event_items = get_ledger_event_items(blocks)

        if not check_production_registration(serial_no, blocks):
            reasons.append(
                "Serial has no MANUFACTURED event in a PRODUCTION block."
            )

        sql_events = get_sql_events(cursor, serial_no)

        reasons.extend(check_block_chain(blocks))

        reasons.extend(
            check_event_hashes(
                sql_events,
                ledger_event_items,
            )
        )

        continuity_reasons = check_continuity(
            cursor,
            sql_events,
        )

        scan_reasons = check_scan_history(
            mongo_db,
            serial_no,
            current_scan_time,
            lat,
            lon,
        )

        sale_reasons = check_previous_sale(sql_events)

        reasons.extend(continuity_reasons)
        reasons.extend(scan_reasons)
        reasons.extend(sale_reasons)

        if reasons:
            if any(
                reason.startswith(
                    (
                        "QR ",
                        "Serial has no MANUFACTURED",
                        "SQL event hash mismatch",
                        "Ledger event hash mismatch",
                        "Event ",
                        "Previous hash mismatch",
                        "Block hash mismatch",
                        "Unexpected block index",
                    )
                )
                for reason in reasons
            ):
                verdict = "FAKE"
            else:
                verdict = "SUSPICIOUS"
        else:
            verdict = "GENUINE"

        if pack["expiry_date"] < date.today():
            reasons.append("Medicine batch has expired.")

        if (
            pack["qc_status"] == "RECALLED"
            or pack["status"] == "RECALLED"
        ):
            reasons.append("Medicine batch or pack has been recalled.")

        route = get_route(cursor, serial_no)

        save_scan(
            mongo_db,
            serial_no,
            verdict,
            reasons,
            current_scan_time,
            city,
            lat,
            lon,
        )

        return {
            "serial_no": serial_no,
            "verdict": verdict,
            "reasons": reasons,
            "route": route,
        }

    finally:
        if cursor is not None:
            cursor.close()

        connection.close()


def main():
    parser = argparse.ArgumentParser(
        description="Verify a pharmaceutical pack serial."
    )

    parser.add_argument("serial_no")
    parser.add_argument("--gtin")
    parser.add_argument("--batch-no")
    parser.add_argument("--expiry")
    parser.add_argument("--city")
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lon", type=float)

    args = parser.parse_args()

    result = verify(
        serial_no=args.serial_no,
        qr_gtin=args.gtin,
        qr_batch_no=args.batch_no,
        qr_expiry=args.expiry,
        city=args.city,
        lat=args.lat,
        lon=args.lon,
    )

    print(json.dumps(result, indent=4, default=str))


if __name__ == "__main__":
    main()
