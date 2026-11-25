
from unittest.mock import patch

from common.config import get_mysql, get_mongo_db
from ledger.verify import verify


def fetch_serials(query):
    connection = get_mysql()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(query)
        return [row["serial_no"] for row in cursor.fetchall()]
    finally:
        cursor.close()
        connection.close()


def run_case(label, serial_no, expected):
    with patch("ledger.verify.save_scan"):
        result = verify(serial_no)

    actual = result["verdict"]
    passed = actual == expected

    print(f"\n{label}")
    print(f"serial:   {serial_no}")
    print(f"expected: {expected}")
    print(f"actual:   {actual}")
    print(f"result:   {'PASS' if passed else 'FAIL'}")

    if result.get("reasons"):
        print("reasons:")
        for reason in result["reasons"]:
            print(f"  - {reason}")

    return passed


def main():
    mongo_db = get_mongo_db()

    cloned = fetch_serials("""
        SELECT serial_no
        FROM injected_counterfeit
        WHERE scenario_type = 'CLONED_SERIAL'
          AND serial_no IS NOT NULL
        ORDER BY serial_no
        LIMIT 1
    """)

    invented = fetch_serials("""
        SELECT serial_no
        FROM injected_counterfeit
        WHERE scenario_type = 'INVENTED_SERIAL'
          AND serial_no IS NOT NULL
        ORDER BY serial_no
        LIMIT 1
    """)

    genuine_candidates = fetch_serials("""
        SELECT p.serial_no
        FROM pack p
        JOIN batch b ON b.batch_id = p.batch_id
        WHERE p.status = 'IN_STOCK'
          AND b.expiry_date >= CURDATE()
          AND b.qc_status <> 'RECALLED'
          AND NOT EXISTS (
              SELECT 1
              FROM trace_event e
              WHERE e.serial_no = p.serial_no
                AND e.event_type = 'SOLD'
          )
          AND NOT EXISTS (
              SELECT 1
              FROM injected_counterfeit ic
              WHERE ic.serial_no = p.serial_no
          )
        ORDER BY p.serial_no
        LIMIT 100
    """)

    if not cloned:
        raise RuntimeError(
            "No CLONED_SERIAL example found in injected_counterfeit."
        )

    if not invented:
        raise RuntimeError(
            "No INVENTED_SERIAL example found in injected_counterfeit."
        )

    genuine = None

    for candidate in genuine_candidates:
        if mongo_db["scan_logs"].count_documents(
            {"serial_no": candidate}
        ) != 0:
            continue

        with patch("ledger.verify.save_scan"):
            result = verify(candidate)

        if result["verdict"] == "GENUINE":
            genuine = candidate
            break

    if genuine is None:
        raise RuntimeError(
            "Could not find a clean, unscanned genuine pack "
            "among the first 100 candidates."
        )

    connection = get_mysql()
    cursor = connection.cursor()

    try:
        cursor.execute(
            "SELECT 1 FROM pack WHERE serial_no = %s LIMIT 1",
            (invented[0],),
        )

        if cursor.fetchone():
            raise RuntimeError(
                "The selected INVENTED_SERIAL is present in pack."
            )
    finally:
        cursor.close()
        connection.close()

    results = [
        run_case("TC01 - genuine serial", genuine, "GENUINE"),
        run_case("TC02 - cloned serial", cloned[0], "SUSPICIOUS"),
        run_case("TC03 - invented serial", invented[0], "FAKE"),
    ]

    print("\nVERIFY TEST SUMMARY")
    print(f"Passed: {sum(results)}/{len(results)}")
    print(f"Failed: {len(results) - sum(results)}/{len(results)}")

    if not all(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
