"""
Settings for the GUI, read from the same .env file the test runner uses.

Keys used (all optional except the admin password):
  MYSQL_HOST                default localhost
  MONGO_URI                 default mongodb://localhost:27017
  DB_NAME                   default pharma_counterfeit_db  (the MAIN database)
  MYSQL_ADMIN_USER          default admin
  MYSQL_ADMIN_PASSWORD      needed: the "system account" for lookups,
                            verification, sealing and reconciliation
  MYSQL_APP_PASSWORD, MYSQL_P5_PASSWORD, MYSQL_P23_PASSWORD,
  MYSQL_DETECTION_PASSWORD, MYSQL_LEDGER_PASSWORD, MYSQL_READONLY_PASSWORD
                            only for the "compare all accounts" table in the
                            Security lab. Logging in always asks for the
                            password; MySQL itself checks it.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env_file(path=ROOT / ".env"):
    """Read KEY=VALUE lines into os.environ (values already set win)."""
    if not path.exists():
        return False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)
    return True


ENV_FOUND = load_env_file()

# The GUI always works on the main database, never the test one.
os.environ.setdefault("DB_NAME", "pharma_counterfeit_db")
DB_NAME = os.environ["DB_NAME"]
MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
ADMIN_USER = os.environ.get("MYSQL_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("MYSQL_ADMIN_PASSWORD", "")

# Her modules (verify.py, reconcile.py, ledger_writer.py) connect through
# common.config, which reads MYSQL_USER / MYSQL_PASSWORD. They run as the
# system account: these are system jobs, not actions of the logged-in user.
os.environ["MYSQL_USER"] = ADMIN_USER
os.environ["MYSQL_PASSWORD"] = ADMIN_PASSWORD


# The MySQL accounts made by sessions/09_create_demo_users.sql.
#   key: MySQL user name
#   who: what the account stands for in the demo
#   participant: the participant it is tied to (p_<id> accounts), else None
#   env: .env key holding its password (used only by the Security lab matrix)
ACCOUNTS = [
    {"user": ADMIN_USER, "who": "Administrator (full access to the project database)",
     "role": "role_admin", "participant": None, "env": "MYSQL_ADMIN_PASSWORD"},
    {"user": "app", "who": "Operations desk: acts for distributors, quality control and recalls",
     "role": "role_app", "participant": None, "env": "MYSQL_APP_PASSWORD"},
    {"user": "p_5", "who": "Manufacturer M1 (participant 5)",
     "role": "role_manufacturer", "participant": 5, "env": "MYSQL_P5_PASSWORD"},
    {"user": "p_23", "who": "Retailer R1 (participant 23)",
     "role": "role_retailer", "participant": 23, "env": "MYSQL_P23_PASSWORD"},
    {"user": "detection", "who": "Detection analyst (reads data, writes flags, never sees the answer key)",
     "role": "role_detection", "participant": None, "env": "MYSQL_DETECTION_PASSWORD"},
    {"user": "ledger", "who": "Ledger service (reads data, may only mark rows as sealed)",
     "role": "role_ledger", "participant": None, "env": "MYSQL_LEDGER_PASSWORD"},
    {"user": "readonly", "who": "Read-only viewer (views only)",
     "role": "role_readonly", "participant": None, "env": "MYSQL_READONLY_PASSWORD"},
]
ACCOUNT_BY_USER = {a["user"]: a for a in ACCOUNTS}


def account_password_from_env(account):
    return os.environ.get(account["env"], "")
