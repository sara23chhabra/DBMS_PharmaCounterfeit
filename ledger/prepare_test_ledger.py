
"""Prepare the separate test ledger in MySQL and MongoDB."""

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def load_env_file(path):
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


def require_env(*keys):
    missing = [key for key in keys if not os.environ.get(key)]

    if missing:
        raise RuntimeError("Missing .env values: " + ", ".join(missing))


def main():
    load_env_file(ROOT / ".env")

    test_db = os.environ.get("TEST_DB_NAME", "pharma_counterfeit_test")

    require_env(
        "MYSQL_HOST",
        "MYSQL_ADMIN_USER",
        "MYSQL_ADMIN_PASSWORD",
        "MONGO_URI",
    )

    # Use the admin account for preparing the test ledger.
    os.environ["MYSQL_USER"] = os.environ["MYSQL_ADMIN_USER"]
    os.environ["MYSQL_PASSWORD"] = os.environ["MYSQL_ADMIN_PASSWORD"]

    sys.path.insert(0, str(ROOT))

    from common import config

    # Make both MySQL and MongoDB connections use the test database.
    config.DB_NAME = test_db

    from ledger.ledger_writer import run

    print("PHARMA COUNTERFEIT - TEST LEDGER PREPARATION")
    print(f"MySQL database: {test_db}")
    print(f"MongoDB database: {test_db}")
    print()
    print("Starting ledger writer...")
    print()

    collection = run()

    print()
    print("Test ledger preparation completed.")
    print(f"Total blocks in test ledger: {collection.count_documents({})}")


if __name__ == "__main__":
    main()
