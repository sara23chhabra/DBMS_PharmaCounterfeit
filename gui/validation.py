"""
Form checks done before anything is sent to the database.

Each function takes the form values and returns {field: message} for every
problem (empty dict = fine). The screen shows all messages at once: a summary
box at the top and each message under its field, keeping what was typed.

These checks are for the user's convenience. The database enforces the same
rules again (constraints, triggers, procedures), so turning the form checks
off in the sidebar shows the database refusing bad data on its own.
"""

import re
from datetime import date

SERIAL_RE = re.compile(r"^[A-Z0-9]{4,20}$")
BATCH_NO_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,29}$")
GTIN_RE = re.compile(r"^[0-9]{13}$")
MAX_PACKS_PER_BATCH = 2000


def parse_serial_list(text):
    """Split pasted serials on commas, spaces or new lines; upper-case them."""
    return [s.strip().upper() for s in re.split(r"[\s,;]+", text or "") if s.strip()]


def bad_serials(serials):
    return [s for s in serials if not SERIAL_RE.match(s)]


def parse_id_list(text):
    """'3, 7 12' -> [3, 7, 12]; returns None if something is not a whole number."""
    parts = [p for p in re.split(r"[\s,;]+", text or "") if p]
    if not all(p.isdigit() for p in parts):
        return None
    return [int(p) for p in parts]


def check_batch(batch_no, mfg_date, expiry_date, quantity, lot_ids, extra_lots_text):
    e = {}
    if not batch_no:
        e["batch_no"] = "Enter a batch number."
    elif not BATCH_NO_RE.match(batch_no):
        e["batch_no"] = "Use 3 to 30 capital letters, digits or hyphens, e.g. VL2611-101."
    if mfg_date is None:
        e["mfg_date"] = "Choose the manufacturing date."
    elif mfg_date > date.today():
        e["mfg_date"] = "The manufacturing date cannot be in the future."
    if expiry_date is None:
        e["expiry_date"] = "Choose the expiry date."
    elif mfg_date is not None and expiry_date <= mfg_date:
        e["expiry_date"] = "The expiry date must be after the manufacturing date."
    if quantity is None or quantity < 1:
        e["quantity"] = "Make at least 1 pack."
    elif quantity > MAX_PACKS_PER_BATCH:
        e["quantity"] = f"At most {MAX_PACKS_PER_BATCH} packs per batch in this demo."
    extra = parse_id_list(extra_lots_text)
    if extra is None:
        e["extra_lots"] = "Lot IDs must be whole numbers separated by commas."
    elif not lot_ids and not extra:
        e["lots"] = "Choose at least one raw-material lot."
    return e


def check_dispatch(to_id, serials):
    e = {}
    if not to_id:
        e["to_id"] = "Choose who receives the shipment."
    if not serials:
        e["serials"] = "Choose or type at least one serial number."
    else:
        bad = bad_serials(serials)
        if bad:
            e["serials"] = f"Not a valid serial (4-20 capital letters or digits): {', '.join(bad[:5])}"
        elif len(set(serials)) != len(serials):
            e["serials"] = "The same serial appears twice."
    return e


def check_receive(shipment_id, scanned):
    e = {}
    if not shipment_id:
        e["shipment_id"] = "Choose the shipment that arrived."
    bad = bad_serials(scanned)
    if bad:
        e["extra"] = f"Not a valid serial (4-20 capital letters or digits): {', '.join(bad[:5])}"
    return e


def check_sell(serial):
    e = {}
    if not serial:
        e["serial"] = "Choose or type the serial number on the pack."
    elif not SERIAL_RE.match(serial):
        e["serial"] = "A serial number is 4-20 capital letters or digits, e.g. FK38QD9S4VXK."
    return e


def check_verify(serial, gtin, batch_no, expiry_text):
    e = {}
    if not serial:
        e["serial"] = "Enter the serial number printed under the QR code."
    elif not SERIAL_RE.match(serial):
        e["serial"] = "A serial number is 4-20 capital letters or digits only, e.g. FK38QD9S4VXK."
    if gtin and not GTIN_RE.match(gtin):
        e["gtin"] = "A GTIN is exactly 13 digits."
    if batch_no and not BATCH_NO_RE.match(batch_no):
        e["batch_no"] = "Use the batch number as printed, e.g. VL2601-001."
    if expiry_text:
        try:
            date.fromisoformat(expiry_text)
        except ValueError:
            e["expiry"] = "Write the date as YYYY-MM-DD, e.g. 2028-06-30."
    return e


def check_batch_id(batch_id, field="batch_id"):
    if not batch_id or batch_id < 1:
        return {field: "Choose a batch."}
    return {}
