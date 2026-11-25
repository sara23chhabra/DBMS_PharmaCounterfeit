
from contextlib import redirect_stdout
from io import StringIO

from common.config import get_mysql
from ledger import tamper_demo
from ledger.reconcile import run_reconciliation


def get_original_records():
    connection = get_mysql()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT event_id, event_time
            FROM trace_event
            WHERE ledger_synced = TRUE AND event_hash IS NOT NULL
            ORDER BY event_id
            LIMIT 1
        """)
        event = cursor.fetchone()

        cursor.execute("""
            SELECT lot_id, quantity_received_kg
            FROM material_lot
            WHERE ledger_synced = TRUE AND lot_hash IS NOT NULL
            ORDER BY lot_id
            LIMIT 1
        """)
        lot = cursor.fetchone()

        cursor.execute("""
            SELECT batch_id, expiry_date
            FROM batch
            WHERE ledger_synced = TRUE AND batch_hash IS NOT NULL
            ORDER BY batch_id
            LIMIT 1
        """)
        batch = cursor.fetchone()

        if not event or not lot or not batch:
            raise RuntimeError(
                "No suitable sealed event, lot, and batch found."
            )

        return event, lot, batch

    finally:
        cursor.close()
        connection.close()


def force_restore(event, lot, batch):
    connection = get_mysql()
    cursor = connection.cursor()

    try:
        cursor.execute("SET @tamper_demo = 1")

        cursor.execute(
            "UPDATE trace_event SET event_time = %s WHERE event_id = %s",
            (event["event_time"], event["event_id"]),
        )

        cursor.execute(
            "UPDATE material_lot SET quantity_received_kg = %s WHERE lot_id = %s",
            (lot["quantity_received_kg"], lot["lot_id"]),
        )

        cursor.execute(
            "UPDATE batch SET expiry_date = %s WHERE batch_id = %s",
            (batch["expiry_date"], batch["batch_id"]),
        )

        cursor.execute("SET @tamper_demo = NULL")
        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


def main():
    originals = get_original_records()
    demo_output = StringIO()

    try:
        with redirect_stdout(demo_output):
            tamper_demo.main()

    finally:
        force_restore(*originals)

    output = demo_output.getvalue()
    print(output)

    required_evidence = (
        "event_id",
        "lot_id",
        "batch_id",
        "HASH_MISMATCH",
    )

    missing = [
        item for item in required_evidence
        if item not in output
    ]

    if missing:
        print(f"RESULT: FAIL - tamper evidence missing: {missing}")
        raise SystemExit(1)

    print("\nChecking the database after restoration...")

    findings = run_reconciliation()

    if findings:
        print("RESULT: FAIL - reconciliation still reports findings.")

        for finding in findings:
            print(finding)

        raise SystemExit(1)

    print(
        "RESULT: PASS - tamper was detected "
        "and original values are restored."
    )


if __name__ == "__main__":
    main()
