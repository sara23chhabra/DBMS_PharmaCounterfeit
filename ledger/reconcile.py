
from datetime import datetime

from common.config import get_mysql, get_mongo_db
from common.hashing import (
    GENESIS_HASH,
    lot_hash,
    batch_hash,
    event_hash,
    block_hash,
)


def get_blocks(mongo_db):
    return list(
        mongo_db["ledger_blocks"].find(
            {},
            {"_id": 0},
        ).sort("block_index", 1)
    )


def build_ledger_items(blocks):
    items = {
        "lot": {},
        "batch": {},
        "event": {},
    }

    for block in blocks:
        for item in block.get("items", []):
            kind = item.get("kind")
            item_id = item.get("id")

            if kind in items and item_id is not None:
                items[kind].setdefault(item_id, []).append(item)

    return items


def check_chain(blocks):
    findings = []

    expected_index = 0
    previous_hash = GENESIS_HASH

    for block in blocks:
        index = block.get("block_index")

        if index != expected_index:
            findings.append({
                "type": "CHAIN_BROKEN",
                "block_index": index,
                "message": (
                    f"Expected block index {expected_index}, "
                    f"found {index}."
                ),
            })

        if block.get("prev_block_hash") != previous_hash:
            findings.append({
                "type": "CHAIN_BROKEN",
                "block_index": index,
                "message": (
                    f"Previous hash mismatch at block {index}."
                ),
            })

        item_hashes = [
            item.get("hash", "")
            for item in block.get("items", [])
        ]

        calculated_hash = block_hash(
            index,
            block.get("timestamp"),
            block.get("block_type"),
            item_hashes,
            block.get("prev_block_hash"),
        )

        if calculated_hash != block.get("block_hash"):
            findings.append({
                "type": "CHAIN_BROKEN",
                "block_index": index,
                "message": f"Block hash mismatch at block {index}.",
            })

        previous_hash = block.get("block_hash")
        expected_index += 1

    return findings


def fetch_lots(cursor):
    cursor.execute("""
        SELECT
            lot_id,
            lot_no,
            material_name,
            quantity_sent_kg,
            quantity_received_kg,
            supplier_id,
            manufacturer_id,
            received_date,
            coa_verified,
            lot_hash,
            ledger_synced
        FROM material_lot
    """)

    return cursor.fetchall()


def fetch_batches(cursor):
    cursor.execute("""
        SELECT
            batch_id,
            drug_id,
            manufacturer_id,
            batch_no,
            mfg_date,
            expiry_date,
            quantity,
            batch_hash,
            ledger_synced
        FROM batch
    """)

    batches = cursor.fetchall()

    for batch in batches:
        cursor.execute("""
            SELECT lot_id
            FROM batch_material
            WHERE batch_id = %s
            ORDER BY lot_id
        """, (batch["batch_id"],))

        batch["lot_ids"] = [
            row["lot_id"]
            for row in cursor.fetchall()
        ]

    return batches


def fetch_events(cursor):
    cursor.execute("""
        SELECT
            e.event_id,
            e.serial_no,
            e.event_type,
            e.shipment_id,
            e.event_time,
            e.event_hash,
            e.ledger_synced,
            CASE
                WHEN e.shipment_id IS NOT NULL
                    THEN l.from_participant
                ELSE b.manufacturer_id
            END AS from_id,
            CASE
                WHEN e.shipment_id IS NOT NULL
                    THEN l.to_participant
                WHEN e.event_type = 'RECALLED'
                    THEN p.current_owner
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
    """)

    return cursor.fetchall()


def add_flag(cursor, rule_code, event_id=None, lot_id=None):
    query = """
        SELECT flag_id
        FROM anomaly_flag
        WHERE rule_code = %s
          AND event_id <=> %s
          AND lot_id <=> %s
          AND shipment_id IS NULL
          AND link_id IS NULL
          AND serial_no IS NULL
          AND resolved = FALSE
        LIMIT 1
    """

    cursor.execute(query, (rule_code, event_id, lot_id))

    if cursor.fetchone():
        return

    cursor.execute("""
        INSERT INTO anomaly_flag (
            rule_code,
            event_id,
            lot_id,
            severity,
            detected_at,
            resolved
        )
        VALUES (%s, %s, %s, 'HIGH', NOW(), FALSE)
    """, (rule_code, event_id, lot_id))


def check_lots(cursor, ledger_items, findings):
    lots = fetch_lots(cursor)
    sql_ids = set()

    for lot in lots:
        lot_id = lot["lot_id"]
        sql_ids.add(lot_id)

        calculated = lot_hash(
            lot["lot_id"],
            lot["lot_no"],
            lot["material_name"],
            lot["quantity_sent_kg"],
            lot["quantity_received_kg"],
            lot["supplier_id"],
            lot["manufacturer_id"],
            lot["received_date"],
            lot["coa_verified"],
        )

        matching = ledger_items["lot"].get(lot_id, [])

        if not lot["ledger_synced"] or not matching:
            findings.append({
                "type": "LEDGER_MISSING",
                "kind": "lot",
                "id": lot_id,
                "message": f"Lot {lot_id} is not sealed in the ledger.",
            })

        if lot["lot_hash"] != calculated:
            findings.append({
                "type": "HASH_MISMATCH",
                "kind": "lot",
                "id": lot_id,
                "message": f"Lot hash mismatch for lot_id {lot_id}.",
            })

        for item in matching:
            if item.get("hash") != calculated:
                findings.append({
                    "type": "HASH_MISMATCH",
                    "kind": "lot",
                    "id": lot_id,
                    "message": (
                        f"Ledger hash mismatch for lot_id {lot_id}."
                    ),
                })
                break

    for lot_id in ledger_items["lot"]:
        if lot_id not in sql_ids:
            findings.append({
                "type": "LEDGER_MISSING",
                "kind": "lot",
                "id": lot_id,
                "message": (
                    f"Ledger contains lot {lot_id}, "
                    "but no matching MySQL row exists."
                ),
            })

    return sql_ids


def check_batches(cursor, ledger_items, findings):
    batches = fetch_batches(cursor)
    sql_ids = set()

    for batch in batches:
        batch_id = batch["batch_id"]
        sql_ids.add(batch_id)

        calculated = batch_hash(
            batch["batch_id"],
            batch["drug_id"],
            batch["manufacturer_id"],
            batch["batch_no"],
            batch["mfg_date"],
            batch["expiry_date"],
            batch["quantity"],
            batch["lot_ids"],
        )

        matching = ledger_items["batch"].get(batch_id, [])

        if not batch["ledger_synced"] or not matching:
            findings.append({
                "type": "LEDGER_MISSING",
                "kind": "batch",
                "id": batch_id,
                "message": (
                    f"Batch {batch_id} is not sealed in the ledger."
                ),
            })

        if batch["batch_hash"] != calculated:
            findings.append({
                "type": "HASH_MISMATCH",
                "kind": "batch",
                "id": batch_id,
                "message": (
                    f"Batch hash mismatch for batch_id {batch_id}."
                ),
            })

        for item in matching:
            if item.get("hash") != calculated:
                findings.append({
                    "type": "HASH_MISMATCH",
                    "kind": "batch",
                    "id": batch_id,
                    "message": (
                        f"Ledger hash mismatch for batch_id {batch_id}."
                    ),
                })
                break

    for batch_id in ledger_items["batch"]:
        if batch_id not in sql_ids:
            findings.append({
                "type": "LEDGER_MISSING",
                "kind": "batch",
                "id": batch_id,
                "message": (
                    f"Ledger contains batch {batch_id}, "
                    "but no matching MySQL row exists."
                ),
            })

    return sql_ids


def check_events(cursor, ledger_items, findings):
    events = fetch_events(cursor)
    sql_ids = set()

    for event in events:
        event_id = event["event_id"]
        sql_ids.add(event_id)

        calculated = event_hash(
            event["event_id"],
            event["serial_no"],
            event["event_type"],
            event["from_id"],
            event["to_id"],
            event["shipment_id"],
            event["event_time"],
        )

        matching = ledger_items["event"].get(event_id, [])

        if not event["ledger_synced"] or not matching:
            findings.append({
                "type": "LEDGER_MISSING",
                "kind": "event",
                "id": event_id,
                "message": (
                    f"Event {event_id} is not sealed in the ledger."
                ),
            })

        if event["event_hash"] != calculated:
            findings.append({
                "type": "HASH_MISMATCH",
                "kind": "event",
                "id": event_id,
                "message": (
                    f"Event hash mismatch for event_id {event_id}."
                ),
            })

        for item in matching:
            if item.get("hash") != calculated:
                findings.append({
                    "type": "HASH_MISMATCH",
                    "kind": "event",
                    "id": event_id,
                    "message": (
                        f"Ledger hash mismatch for event_id {event_id}."
                    ),
                })
                break

    for event_id in ledger_items["event"]:
        if event_id not in sql_ids:
            findings.append({
                "type": "LEDGER_MISSING",
                "kind": "event",
                "id": event_id,
                "message": (
                    f"Ledger contains event {event_id}, "
                    "but no matching MySQL row exists."
                ),
            })

    return sql_ids


def write_flags(cursor, findings):
    for finding in findings:
        finding_type = finding["type"]
        kind = finding.get("kind")
        item_id = finding.get("id")

        if finding_type == "CHAIN_BROKEN":
            add_flag(cursor, "CHAIN_BROKEN")

        elif finding_type == "LEDGER_MISSING":
            if kind == "lot":
                add_flag(cursor, "LEDGER_MISSING", lot_id=item_id)
            elif kind == "event":
                add_flag(cursor, "LEDGER_MISSING", event_id=item_id)
            else:
                add_flag(cursor, "LEDGER_MISSING")

        elif finding_type == "HASH_MISMATCH":
            if kind == "lot":
                add_flag(cursor, "HASH_MISMATCH", lot_id=item_id)
            elif kind == "event":
                add_flag(cursor, "HASH_MISMATCH", event_id=item_id)
            else:
                add_flag(cursor, "HASH_MISMATCH")


def run_reconciliation():
    connection = get_mysql()
    mongo_db = get_mongo_db()

    try:
        cursor = connection.cursor(dictionary=True)

        blocks = get_blocks(mongo_db)
        ledger_items = build_ledger_items(blocks)

        findings = []

        findings.extend(check_chain(blocks))

        check_lots(cursor, ledger_items, findings)
        check_batches(cursor, ledger_items, findings)
        check_events(cursor, ledger_items, findings)

        write_flags(cursor, findings)
        connection.commit()

        print("\nRECONCILIATION REPORT")
        print("=====================")

        if not findings:
            print("No reconciliation issues found.")
        else:
            for finding in findings:
                print(
                    f"[{finding['type']}] "
                    f"{finding['message']}"
                )

        print("\nSUMMARY")
        print("-------")

        for finding_type in (
            "LEDGER_MISSING",
            "HASH_MISMATCH",
            "CHAIN_BROKEN",
        ):
            count = sum(
                finding["type"] == finding_type
                for finding in findings
            )

            print(f"{finding_type}: {count}")

        print(f"Total findings: {len(findings)}")

        return findings

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    run_reconciliation()
