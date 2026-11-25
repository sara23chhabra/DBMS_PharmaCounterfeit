
from ledger.reconcile import run_reconciliation


def main():
    print("BASELINE LEDGER RECONCILIATION TEST")
    print("Expected: no findings on the restored, untampered database.")

    findings = run_reconciliation()

    if findings:
        print("\nRESULT: FAIL")
        print(f"Unexpected findings: {len(findings)}")

        for finding in findings:
            print(finding)

        raise SystemExit(1)

    print("\nRESULT: PASS")
    print("No ledger missing, hash mismatch, or chain broken findings.")


if __name__ == "__main__":
    main()
