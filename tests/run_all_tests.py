"""Run Pharma Counterfeit security tests S1-S9 and ledger tests L1-L8.

Run from the project root:
    python tests/run_all_tests.py

All results are written to sessions/all_tests_output.txt.
The runner targets TEST_DB_NAME in MySQL and MongoDB only.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import traceback
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "sessions"
OUTPUT_FILE = OUTPUT_DIR / "all_tests_output.txt"


def load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE entries without requiring python-dotenv."""
    if not path.exists():
        raise FileNotFoundError(f"Missing .env file: {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def require_env(*keys: str) -> None:
    missing = [key for key in keys if not os.environ.get(key)]
    if missing:
        raise RuntimeError("Missing .env values: " + ", ".join(missing))


load_env_file(ROOT / ".env")

DB_NAME = os.environ.get("TEST_DB_NAME", "pharma_counterfeit_test")
os.environ["DB_NAME"] = DB_NAME
os.environ["MYSQL_USER"] = os.environ.get("MYSQL_ADMIN_USER", "admin")
os.environ["MYSQL_PASSWORD"] = os.environ.get("MYSQL_ADMIN_PASSWORD", "")

require_env(
    "MYSQL_HOST",
    "MONGO_URI",
    "MYSQL_READONLY_PASSWORD",
    "MYSQL_DETECTION_PASSWORD",
    "MYSQL_APP_PASSWORD",
    "MYSQL_P5_PASSWORD",
    "MYSQL_P23_PASSWORD",
    "MYSQL_LEDGER_PASSWORD",
    "MYSQL_ADMIN_PASSWORD",
)

sys.path.insert(0, str(ROOT))

import mysql.connector
from mysql.connector import Error as MySQLError
from common import config
from common.config import get_mongo_db
from ledger.reconcile import run_reconciliation
from ledger.verify import verify


RESULTS: list[tuple[str, str, str]] = []
LOG: list[str] = []


def log(message: str = "") -> None:
    LOG.append(message)


def mysql_connection(user_key: str, password_key: str):
    return mysql.connector.connect(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        user=os.environ[user_key],
        password=os.environ[password_key],
        database=DB_NAME,
        autocommit=False,
    )


def record(test_id: str, passed: bool, detail: str) -> None:
    status = "PASS" if passed else "FAIL"
    RESULTS.append((test_id, status, detail.replace("\n", " ")))
    log(f"[{status}] {test_id}: {detail}")


def run_expected_denial(test_id: str, user_key: str, password_key: str,
                        sql: str, expected_code: int) -> None:
    conn = None
    try:
        conn = mysql_connection(user_key, password_key)
        cur = conn.cursor()
        cur.execute(sql)
        conn.rollback()
        record(test_id, False, f"statement unexpectedly succeeded; expected MySQL error {expected_code}")
    except MySQLError as exc:
        code = getattr(exc, "errno", None)
        passed = code == expected_code
        record(test_id, passed, f"received MySQL error {code}: {exc.msg}")
    except Exception as exc:
        record(test_id, False, f"unexpected error: {exc}")
    finally:
        if conn is not None:
            conn.close()



def run_security_tests() -> None:
    log("SECURITY TESTS S1-S9")
    log("Reading SQL tests from tests/security_tests.sql")
    log("Target database: " + DB_NAME)

    sql_file = ROOT / "tests" / "security_tests.sql"

    if not sql_file.exists():
        raise FileNotFoundError(f"Security SQL file not found: {sql_file}")

    sql_text = sql_file.read_text(encoding="utf-8")

    section_matches = list(
        re.finditer(r"(?m)^--\s*(S[1-9])\s*[-:]", sql_text)
    )

    sections = {}

    for index, match in enumerate(section_matches):
        section_id = match.group(1)
        start = match.start()
        end = (
            section_matches[index + 1].start()
            if index + 1 < len(section_matches)
            else len(sql_text)
        )

        section_text = sql_text[start:end]

        account_match = re.search(
            r"Connect as:\s*(\w+)",
            section_text,
            re.IGNORECASE,
        )

        if not account_match:
            record(section_id, False, "SQL section has no Connect as account declaration")
            continue

        account = account_match.group(1).lower()

        cleaned = re.sub(r"(?m)^\s*--.*$", "", section_text)

        statements = [
            statement.strip()
            for statement in cleaned.split(";")
            if statement.strip()
        ]

        sections[section_id] = (account, statements)

    account_keys = {
        "readonly": ("MYSQL_READONLY_USER", "MYSQL_READONLY_PASSWORD"),
        "detection": ("MYSQL_DETECTION_USER", "MYSQL_DETECTION_PASSWORD"),
        "app": ("MYSQL_APP_USER", "MYSQL_APP_PASSWORD"),
        "p_5": ("MYSQL_P5_USER", "MYSQL_P5_PASSWORD"),
        "p_23": ("MYSQL_P23_USER", "MYSQL_P23_PASSWORD"),
        "ledger": ("MYSQL_LEDGER_USER", "MYSQL_LEDGER_PASSWORD"),
    }

    expected_denials = {
        "S1": 1142,
        "S2": 1142,
        "S4": 1142,
        "S5": 1142,
        "S8": 1143,
        "S9": 1142,
    }

    for test_id in [f"S{i}" for i in range(1, 10)]:
        if test_id not in sections:
            if not any(result[0] == test_id for result in RESULTS):
                record(test_id, False, "test section missing from security_tests.sql")
            continue

        account, statements = sections[test_id]

        if account not in account_keys:
            record(test_id, False, f"unknown MySQL account in SQL file: {account}")
            continue

        if not statements:
            record(test_id, False, "no SQL statements found in section")
            continue

        user_key, password_key = account_keys[account]
        conn = None

        try:
            conn = mysql_connection(user_key, password_key)
            cur = conn.cursor()

            if test_id in expected_denials:
                try:
                    cur.execute(statements[0])
                    conn.rollback()
                    record(
                        test_id,
                        False,
                        f"statement unexpectedly succeeded; expected MySQL error {expected_denials[test_id]}",
                    )
                except MySQLError as exc:
                    code = getattr(exc, "errno", None)
                    record(
                        test_id,
                        code == expected_denials[test_id],
                        f"received MySQL error {code}; expected {expected_denials[test_id]}: {exc.msg}",
                    )

            elif test_id == "S3":
                if len(statements) < 2:
                    raise RuntimeError("S3 requires both INSERT and verification SELECT")

                cur.execute(statements[0])
                cur.execute(statements[1])
                result = cur.fetchone()

                conn.rollback()

                record(
                    test_id,
                    result is not None,
                    "detection user inserted into anomaly_flag and retrieved the test flag; transaction rolled back",
                )

            elif test_id == "S6":
                if len(statements) < 2:
                    raise RuntimeError("S6 requires two SELECT statements")

                cur.execute(statements[0])
                visible_count = int(cur.fetchone()[0])

                cur.execute(statements[1])
                wrong_owner_count = int(cur.fetchone()[0])

                passed = visible_count == 50 and wrong_owner_count == 0

                record(
                    test_id,
                    passed,
                    f"p_5 sees {visible_count} batches; rows not owned by manufacturer 5: {wrong_owner_count}; expected 50 and 0",
                )

            elif test_id == "S7":
                if len(statements) < 2:
                    raise RuntimeError("S7 requires two SELECT statements")

                cur.execute(statements[0])
                visible_count = int(cur.fetchone()[0])

                cur.execute(statements[1])
                wrong_owner_count = int(cur.fetchone()[0])

                passed = wrong_owner_count == 0

                record(
                    test_id,
                    passed,
                    f"p_23 sees {visible_count} packs; rows not owned by retailer 23: {wrong_owner_count}; expected 0",
                )

            else:
                record(test_id, False, "no execution handler defined for this test")

        except MySQLError as exc:
            if conn is not None:
                conn.rollback()

            record(
                test_id,
                False,
                f"MySQL error {getattr(exc, 'errno', None)}: {exc.msg}",
            )

        except Exception as exc:
            if conn is not None:
                conn.rollback()

            record(test_id, False, f"test execution failed: {exc}")

        finally:
            if conn is not None:
                conn.close()



def admin_connection():
    return mysql_connection("MYSQL_ADMIN_USER", "MYSQL_ADMIN_PASSWORD")


def capture_call(function):
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        result = function()
    captured = stream.getvalue().strip()
    if captured:
        log(captured)
    return result


def reconcile_findings():
    os.environ["MYSQL_USER"] = os.environ["MYSQL_ADMIN_USER"]
    os.environ["MYSQL_PASSWORD"] = os.environ["MYSQL_ADMIN_PASSWORD"]
    config.DB_NAME = DB_NAME
    return capture_call(run_reconciliation)


def find_sealed_records():
    conn = admin_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("""SELECT event_id, serial_no, event_time FROM trace_event
                       WHERE ledger_synced = TRUE AND event_hash IS NOT NULL
                       ORDER BY event_id LIMIT 1""")
        event = cur.fetchone()
        cur.execute("""SELECT lot_id, quantity_received_kg FROM material_lot
                       WHERE ledger_synced = TRUE AND lot_hash IS NOT NULL
                       ORDER BY lot_id LIMIT 1""")
        lot = cur.fetchone()
        cur.execute("""SELECT batch_id, expiry_date FROM batch
                       WHERE ledger_synced = TRUE AND batch_hash IS NOT NULL
                       ORDER BY batch_id LIMIT 1""")
        batch = cur.fetchone()
        if not event or not lot or not batch:
            raise RuntimeError("No sealed event, lot, or batch found. Run the ledger writer on the test database first.")
        return event, lot, batch
    finally:
        conn.close()


def run_append_only_tests(event_id: int) -> None:
    for test_id, statement in (
        ("L1", "UPDATE trace_event SET event_time = DATE_ADD(event_time, INTERVAL 1 SECOND) WHERE event_id = %s"),
        ("L2", "DELETE FROM trace_event WHERE event_id = %s"),
    ):
        conn = admin_connection()
        try:
            cur = conn.cursor()
            try:
                cur.execute(statement, (event_id,))
                conn.rollback()
                record(test_id, False, "admin modification unexpectedly succeeded")
            except MySQLError as exc:
                conn.rollback()
                passed = "APPEND_ONLY" in str(exc)
                record(test_id, passed, f"received trigger response: {exc}")
        except Exception as exc:
            record(test_id, False, f"test failed: {exc}")
        finally:
            conn.close()


def run_mysql_tamper_tests(event, lot, batch) -> None:
    changes = [
        ("L3", "trace_event", "event_time", event["event_id"], event["event_time"],
         "UPDATE trace_event SET event_time = DATE_ADD(event_time, INTERVAL 1 DAY) WHERE event_id = %s",
         "event"),
        ("L4", "material_lot", "quantity_received_kg", lot["lot_id"], lot["quantity_received_kg"],
         "UPDATE material_lot SET quantity_received_kg = quantity_received_kg + 1.00 WHERE lot_id = %s",
         "lot"),
        ("L5", "batch", "expiry_date", batch["batch_id"], batch["expiry_date"],
         "UPDATE batch SET expiry_date = DATE_ADD(expiry_date, INTERVAL 1 DAY) WHERE batch_id = %s",
         "batch"),
    ]
    for test_id, table, column, row_id, original, update_sql, kind in changes:
        conn = admin_connection()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute("SET @tamper_demo = 1")
            cur.execute(update_sql, (row_id,))
            conn.commit()
            findings = reconcile_findings()
            found = any(item.get("type") == "HASH_MISMATCH" and item.get("id") == row_id
                        for item in findings)
            record(test_id, found, f"reconciliation {'detected' if found else 'did not detect'} HASH_MISMATCH for {kind} id {row_id}")
        except Exception as exc:
            conn.rollback()
            record(test_id, False, f"tamper/reconciliation failed: {exc}")
        finally:
            conn.close()


def run_mongo_tamper_test():
    db = get_mongo_db()
    collection = db["ledger_blocks"]
    block = collection.find_one({"items.0": {"$exists": True}}, sort=[("block_index", 1)])
    if not block:
        record("L6", False, "no ledger block with items exists in test MongoDB; run ledger writer first")
        return None
    original_hash = block["items"][0].get("hash")
    collection.update_one({"_id": block["_id"]}, {"$set": {"items.0.hash": "0" * 64}})
    try:
        findings = reconcile_findings()
        detected = any(item.get("type") == "CHAIN_BROKEN" and item.get("block_index") == block["block_index"]
                       for item in findings)
        record("L6", detected, f"reconciliation {'detected' if detected else 'did not detect'} CHAIN_BROKEN at block {block['block_index']}")
    finally:
        collection.update_one({"_id": block["_id"]}, {"$set": {"items.0.hash": original_hash}})
    return block


def run_consumer_verification(serial_no: str) -> None:
    try:
        result = verify(serial_no=serial_no)
        verdict = result.get("verdict")
        record("L7", verdict == "FAKE", f"verify.py returned {verdict} for tampered serial {serial_no}; reasons: {'; '.join(result.get('reasons', []))}")
    except Exception as exc:
        record("L7", False, f"serial verification failed: {exc}")


def restore_and_check(event, lot, batch, mongo_block) -> None:
    conn = admin_connection()
    try:
        cur = conn.cursor()
        cur.execute("SET @tamper_demo = 1")
        cur.execute("UPDATE trace_event SET event_time = %s WHERE event_id = %s",
                    (event["event_time"], event["event_id"]))
        cur.execute("UPDATE material_lot SET quantity_received_kg = %s WHERE lot_id = %s",
                    (lot["quantity_received_kg"], lot["lot_id"]))
        cur.execute("UPDATE batch SET expiry_date = %s WHERE batch_id = %s",
                    (batch["expiry_date"], batch["batch_id"]))
        conn.commit()
    finally:
        conn.close()

    findings = reconcile_findings()
    relevant_ids = {event["event_id"], lot["lot_id"], batch["batch_id"]}
    remaining = [f for f in findings if f.get("type") == "HASH_MISMATCH" and f.get("id") in relevant_ids]
    mongo_ok = True
    if mongo_block:
        db = get_mongo_db()
        block = db["ledger_blocks"].find_one({"_id": mongo_block["_id"]})
        # Reconciliation verifies block hashes and previous hashes after the item hash is restored.
        mongo_ok = bool(block and block["items"][0].get("hash") == mongo_block["items"][0].get("hash"))
    record("L8", not remaining and mongo_ok,
           f"restored MySQL records; remaining relevant hash mismatches={len(remaining)}; Mongo block restored={mongo_ok}")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log("PHARMA COUNTERFEIT DBMS - SECURITY AND LEDGER TESTS")
    log("Started: " + datetime.now().astimezone().isoformat(timespec="seconds"))
    log("MySQL test database: " + DB_NAME)
    log("MongoDB test database: " + DB_NAME)
    log("No main database is intentionally accessed by this runner.")
    log("")

    run_security_tests()
    log("")
    log("LEDGER TESTS L1-L8")

    try:
        config.DB_NAME = DB_NAME
        log("Checking the pre-prepared test ledger...")
        
        collection = get_mongo_db()["ledger_blocks"]

        block_count = collection.count_documents(
        {"items.0": {"$exists": True}}
        )

        if block_count == 0:
            raise RuntimeError(
                "Test ledger is empty. Run ledger/prepare_test_ledger.py first."
            )
        
        log(f"Test ledger is ready with {block_count} blocks.")
        event, lot, batch = find_sealed_records()
        run_append_only_tests(event["event_id"])
        run_mysql_tamper_tests(event, lot, batch)
        mongo_block = run_mongo_tamper_test()
        run_consumer_verification(event["serial_no"])
        restore_and_check(event, lot, batch, mongo_block)
    except Exception as exc:
        record("LEDGER_SETUP", False, f"ledger test setup/runner error: {exc}")
        log(traceback.format_exc())

    log("")
    log("FINAL SUMMARY")
    for test_id, status, detail in RESULTS:
        log(f"{test_id}: {status} - {detail}")
    passed = sum(status == "PASS" for _, status, _ in RESULTS)
    failed = sum(status == "FAIL" for _, status, _ in RESULTS)
    log(f"TOTAL: {passed} passed, {failed} failed, {len(RESULTS)} executed")
    log("Finished: " + datetime.now().astimezone().isoformat(timespec="seconds"))
    OUTPUT_FILE.write_text("\n".join(LOG) + "\n", encoding="utf-8")
    print(f"Tests finished. Output saved to: {OUTPUT_FILE.relative_to(ROOT)}")
    print(f"Passed: {passed} | Failed: {failed} | Executed: {len(RESULTS)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
