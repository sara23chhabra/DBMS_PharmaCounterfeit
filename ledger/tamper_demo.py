
from datetime import datetime, timedelta

from mysql.connector import Error

from common.config import get_mysql
from ledger.reconcile import run_reconciliation


def get_demo_records(cursor):
    cursor.execute("""
        SELECT event_id, event_time
        FROM trace_event
        WHERE ledger_synced = TRUE
          AND event_hash IS NOT NULL
        ORDER BY event_id
        LIMIT 1
    """)
    event = cursor.fetchone()

    cursor.execute("""
        SELECT lot_id, quantity_received_kg
        FROM material_lot
        WHERE ledger_synced = TRUE
          AND lot_hash IS NOT NULL
        ORDER BY lot_id
        LIMIT 1
    """)
    lot = cursor.fetchone()

    cursor.execute("""
        SELECT batch_id, expiry_date
        FROM batch
        WHERE ledger_synced = TRUE
          AND batch_hash IS NOT NULL
        ORDER BY batch_id
        LIMIT 1
    """)
    batch = cursor.fetchone()

    if not event or not lot or not batch:
        raise RuntimeError(
            "No suitable sealed event, lot, or batch was found. "
            "Run the ledger writer first."
        )

    return event, lot, batch


def demonstrate_append_only(cursor, event):
    print("\nSTEP 1: TEST APPEND-ONLY PROTECTION")
    print("----------------------------------")

    event_id = event["event_id"]

    try:
        cursor.execute(
            """
            UPDATE trace_event
            SET event_time = DATE_ADD(event_time, INTERVAL 1 SECOND)
            WHERE event_id = %s
            """,
            (event_id,),
        )

        print(
            "WARNING: The event update was accepted without "
            "the tamper switch."
        )

    except Error as error:
        print("Expected rejection:")
        print(error)

    finally:
        cursor.execute("ROLLBACK")


def tamper_records(cursor, event, lot, batch):
    print("\nSTEP 2: ENABLE TAMPER SWITCH")
    print("----------------------------")

    cursor.execute("SET @tamper_demo = 1")

    event_id = event["event_id"]
    lot_id = lot["lot_id"]
    batch_id = batch["batch_id"]

    cursor.execute(
        """
        UPDATE trace_event
        SET event_time = DATE_ADD(event_time, INTERVAL 1 DAY)
        WHERE event_id = %s
        """,
        (event_id,),
    )

    cursor.execute(
        """
        UPDATE material_lot
        SET quantity_received_kg = quantity_received_kg + 1.00
        WHERE lot_id = %s
        """,
        (lot_id,),
    )

    cursor.execute(
        """
        UPDATE batch
        SET expiry_date = DATE_ADD(expiry_date, INTERVAL 1 DAY)
        WHERE batch_id = %s
        """,
        (batch_id,),
    )

    print(f"Modified event_id: {event_id}")
    print(f"Modified lot_id: {lot_id}")
    print(f"Modified batch_id: {batch_id}")

    return event_id, lot_id, batch_id


def restore_records(cursor, event, lot, batch):
    print("\nSTEP 4: RESTORE ORIGINAL VALUES")
    print("-------------------------------")

    cursor.execute(
        """
        UPDATE trace_event
        SET event_time = %s
        WHERE event_id = %s
        """,
        (event["event_time"], event["event_id"]),
    )

    cursor.execute(
        """
        UPDATE material_lot
        SET quantity_received_kg = %s
        WHERE lot_id = %s
        """,
        (lot["quantity_received_kg"], lot["lot_id"]),
    )

    cursor.execute(
        """
        UPDATE batch
        SET expiry_date = %s
        WHERE batch_id = %s
        """,
        (batch["expiry_date"], batch["batch_id"]),
    )

    cursor.execute("SET @tamper_demo = NULL")

    print("Original event, lot, and batch values restored.")


def main():
    connection = get_mysql()

    try:
        cursor = connection.cursor(dictionary=True)

        event, lot, batch = get_demo_records(cursor)

        demonstrate_append_only(cursor, event)

        event_id, lot_id, batch_id = tamper_records(
            cursor,
            event,
            lot,
            batch,
        )

        connection.commit()

        print("\nSTEP 3: RUN RECONCILIATION")
        print("--------------------------")

        run_reconciliation()

        print("\nSTEP 4: RESTORE ORIGINAL VALUES")
        print("-------------------------------")

        restore_records(cursor, event, lot, batch)
        connection.commit()

        print("\nSTEP 5: RUN RECONCILIATION AGAIN")
        print("--------------------------------")

        findings = run_reconciliation()

        remaining_hash_issues = [
            finding
            for finding in findings
            if (
                finding["type"] == "HASH_MISMATCH"
                and (
                    finding.get("id") in (
                        event_id,
                        lot_id,
                        batch_id,
                    )
                )
            )
        ]

        if remaining_hash_issues:
            print(
                "\nWARNING: Some tampered records still have "
                "hash mismatches."
            )
        else:
            print(
                "\nThe three tampered records now match their "
                "original hashes."
            )

    except Exception:
        connection.rollback()

        try:
            cursor.execute("SET @tamper_demo = NULL")
        except Exception:
            pass

        raise

    finally:
        connection.close()


if __name__ == "__main__":
    main()
