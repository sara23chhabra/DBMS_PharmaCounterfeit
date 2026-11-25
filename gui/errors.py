"""
Turn MySQL errors into plain explanations for the screen.

Every refusal falls in one of four groups, shown with its own heading:
  denied      the account has no permission        (MySQL privileges, 05_roles.sql)
  rule        a business rule refused the action   (SIGNAL in a trigger or procedure)
  constraint  the data broke a table rule          (CHECK, FOREIGN KEY, UNIQUE, 01_schema.sql)
  login / connection / other
The exact MySQL message is always shown too, so nothing is hidden.
"""

import re

# Codes raised by SIGNAL in 02_triggers.sql and 03_procedures.sql
RULES = {
    "WRONG_PARTICIPANT_TYPE": ("A participant of the wrong type was used.", "trigger (02_triggers.sql)"),
    "INVALID_LINK": ("Trading links may only go Supplier -> Manufacturer -> Distributor -> Retailer -> Consumer.",
                     "trigger trg_link_type"),
    "APPEND_ONLY": ("Supply-chain history (trace_event) can never be edited or deleted, even by the administrator.",
                    "trigger trg_trace_event_no_update / no_delete"),
    "LICENSE_NOT_ACTIVE": ("The sender's licence is not ACTIVE, so it may not send anything.",
                           "trigger trg_shipment_license"),
    "NOT_YOUR_ACCOUNT": ("This login belongs to one participant and may act only for that participant.",
                         "stored procedure (caller check)"),
    "NO_LOTS": ("A batch must use at least one raw-material lot.", "stored procedure create_batch"),
    "LOT_NOT_AT_FACTORY": ("One of the lots was delivered to a different factory.", "stored procedure create_batch"),
    "BATCH_NOT_PENDING": ("Only a PENDING batch can be approved.", "stored procedure approve_batch"),
    "BATCH_NOT_FOUND": ("There is no batch with this ID.", "stored procedure"),
    "BATCH_NOT_APPROVED": ("Packs can be made only after quality control has APPROVED the batch.",
                           "stored procedure generate_packs"),
    "PACKS_ALREADY_GENERATED": ("This batch already has its packs.", "stored procedure generate_packs"),
    "NO_LINK": ("These two participants do not trade with each other (no link).", "stored procedure"),
    "USE_SELL_PACK": ("Sales to a consumer are made with 'Sell a pack', not as a shipment.",
                      "stored procedure dispatch_shipment"),
    "NO_SERIALS": ("The list of serial numbers is empty.", "stored procedure"),
    "NOT_OWNER": ("The sender does not hold every pack in the list.", "stored procedure"),
    "NOT_IN_STOCK": ("Every pack must be IN_STOCK (not in transit, sold or recalled).", "stored procedure"),
    "SHIPMENT_NOT_FOUND": ("There is no shipment with this ID.", "stored procedure receive_shipment"),
    "NOT_IN_TRANSIT": ("This shipment has already been received.", "stored procedure receive_shipment"),
    "PACK_NOT_FOUND": ("This serial number is not a registered pack.", "stored procedure sell_pack"),
    "RECALLED": ("This pack belongs to a recalled batch and must not be sold.", "stored procedure sell_pack"),
    "EXPIRED": ("This pack is past its expiry date.", "stored procedure sell_pack"),
    "ALREADY_RECALLED": ("This batch has already been recalled.", "stored procedure recall_batch"),
}

# CHECK constraints in 01_schema.sql
CHECKS = {
    "chk_batch_dates": "The expiry date must be after the manufacturing date.",
    "chk_batch_quantity": "The quantity must be more than 0.",
    "chk_batch_hash": "A batch hash must be 64 characters.",
    "chk_drug_gtin": "A GTIN must be exactly 13 digits.",
    "chk_drug_price": "A pack price must be more than 0.",
    "chk_drug_units": "Units per pack must be more than 0.",
    "chk_license_dates": "A licence must end after it is issued.",
    "chk_license_history_change": "A licence change must change the status.",
    "chk_link_not_self": "A participant cannot trade with itself.",
    "chk_link_risk_range": "A risk score must be between 0 and 1.",
    "chk_material_lot_sent": "The quantity sent must be more than 0 kg.",
    "chk_material_lot_received": "The quantity received must be more than 0 kg.",
    "chk_shipment_times": "A shipment cannot be received before it was sent.",
    "chk_shipment_status_time": "A received shipment must have a receive time.",
    "chk_trace_event_shipment": "MANUFACTURED / RECALLED events have no shipment; the others must have one.",
}

PRIVILEGE_ERRNOS = {1142, 1143, 1370, 1044, 1227, 1356}


def explain(err):
    """
    err: a mysql.connector.Error (or anything with errno and msg).
    Returns a dict: kind, title, detail, enforced_by, raw.
    """
    errno = getattr(err, "errno", None)
    msg = getattr(err, "msg", None) or str(err)
    sqlstate = getattr(err, "sqlstate", None)
    raw = f"ERROR {errno} ({sqlstate}): {msg}" if errno else str(err)

    if errno == 1644 or (sqlstate == "45000"):
        code, _, sentence = msg.partition(":")
        code = code.strip()
        plain, where = RULES.get(code, (sentence.strip() or msg, "trigger or stored procedure"))
        return {"kind": "rule", "title": f"Refused by a database rule: {code}",
                "detail": plain, "enforced_by": where, "raw": raw}

    if errno in PRIVILEGE_ERRNOS:
        m = re.search(r"(\w+) command denied to user '([^']+)'@'[^']+' for (?:column '([^']+)' in )?"
                      r"(?:table|routine) '([^']+)'", msg)
        if m:
            command, user, column, obj = m.groups()
            what = f"column {column} of {obj}" if column else obj
            detail = f"The account '{user}' has no {command} permission on {what}."
        else:
            detail = "This account does not have permission for this action."
        return {"kind": "denied", "title": "Access denied by MySQL",
                "detail": detail, "enforced_by": "MySQL privileges (roles in 05_roles.sql)", "raw": raw}

    if errno == 3819:
        m = re.search(r"constraint '([^']+)'", msg)
        name = m.group(1) if m else "?"
        return {"kind": "constraint", "title": f"Refused by a table rule: {name}",
                "detail": CHECKS.get(name, "A CHECK constraint was violated."),
                "enforced_by": "CHECK constraint (01_schema.sql)", "raw": raw}

    if errno in (1452, 1451, 1216, 1217):
        if errno in (1451, 1217):
            detail = "Other records still refer to this row, so it cannot be removed."
        else:
            m = re.search(r"FOREIGN KEY \(`([^`]+)`\) REFERENCES `([^`]+)`", msg)
            detail = (f"The value given for {m.group(1)} does not exist in {m.group(2)}."
                      if m else "A value refers to a record that does not exist.")
        return {"kind": "constraint", "title": "Refused by a table rule: foreign key",
                "detail": detail, "enforced_by": "FOREIGN KEY (01_schema.sql)", "raw": raw}

    if errno == 1062:
        m = re.search(r"Duplicate entry '([^']*)' for key '([^']+)'", msg)
        detail = (f"'{m.group(1)}' already exists (unique key {m.group(2)})."
                  if m else "This value already exists.")
        return {"kind": "constraint", "title": "Refused by a table rule: duplicate",
                "detail": detail, "enforced_by": "UNIQUE key (01_schema.sql)", "raw": raw}

    if errno in (1048, 1364):
        return {"kind": "constraint", "title": "Refused by a table rule: missing value",
                "detail": "A required value was left empty.", "enforced_by": "NOT NULL (01_schema.sql)",
                "raw": raw}

    if errno in (1264, 1265, 1366, 1292, 1406):
        return {"kind": "constraint", "title": "Refused: value of the wrong type or size",
                "detail": "One of the values does not fit its column (wrong type, too long or out of range).",
                "enforced_by": "column type (01_schema.sql)", "raw": raw}

    if errno == 1045:
        return {"kind": "login", "title": "Login failed",
                "detail": "Wrong user name or password. MySQL checked the password and refused it.",
                "enforced_by": "MySQL authentication", "raw": raw}

    if errno in (2003, 2005, 2013, 2055):
        return {"kind": "connection", "title": "Cannot reach MySQL",
                "detail": "Is MySQL running, and are MYSQL_HOST and the password in .env right?",
                "enforced_by": "-", "raw": raw}

    if errno in (1305, 1146):
        return {"kind": "other", "title": "Missing database object",
                "detail": "A table, view or procedure is missing. Run the SQL files in order (see the guide).",
                "enforced_by": "-", "raw": raw}

    return {"kind": "other", "title": "The database refused the request",
            "detail": msg, "enforced_by": "MySQL", "raw": raw}


def short_verdict(info):
    """One word for tables: BLOCKED (permission), REFUSED (rule or constraint), ERROR."""
    if info["kind"] == "denied":
        return "BLOCKED"
    if info["kind"] in ("rule", "constraint"):
        return "REFUSED"
    return "ERROR"
