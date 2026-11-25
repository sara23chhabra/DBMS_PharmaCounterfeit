"""
Service layer: the only place the GUI talks to MySQL and MongoDB.

Two kinds of connection
  * the USER connection: the MySQL account the person logged in with.
    Every operation (create batch, dispatch, sell, ...) runs through it, so
    MySQL privileges and the procedures' own checks decide what is allowed.
  * the SYSTEM connection: the admin account from .env. Used only for
    drop-down lists (names of drugs, lots, partners), for the consumer
    verification page (consumers have no login), and for the system jobs
    in ledger/ (sealing, reconciliation), exactly as those scripts run today.

No business rule is written here: the stored procedures, triggers, views,
verify.py and reconcile.py make every decision. Each function returns a
Result with either data or an explained error (gui/errors.py).
"""

import contextlib
import io
import json
from datetime import date, datetime, timedelta
from decimal import Decimal

import mysql.connector
from mysql.connector import Error as MySQLError

from gui import settings
from gui.errors import explain, short_verdict

TAMPER_BACKUP = settings.ROOT / "gui" / "tamper_backup.json"


class Result:
    def __init__(self, ok, message="", data=None, error=None, tables=None, log=""):
        self.ok = ok
        self.message = message
        self.data = data
        self.error = error          # dict from errors.explain
        self.tables = tables or []  # list of (title, rows as list of dicts)
        self.log = log              # printed output of her scripts


def failed(err, log=""):
    return Result(False, error=explain(err), log=log)


# ---------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------
def connect(user, password):
    return mysql.connector.connect(host=settings.MYSQL_HOST, user=user, password=password,
                                   database=settings.DB_NAME, autocommit=False,
                                   connection_timeout=10)


def system_connect():
    return connect(settings.ADMIN_USER, settings.ADMIN_PASSWORD)


def check_login(user, password):
    """MySQL checks the password: a failed connect means a failed login."""
    try:
        conn = connect(user, password)
        cur = conn.cursor()
        cur.execute("SELECT CURRENT_USER(), CURRENT_ROLE()")
        row = cur.fetchone()
        current_user, roles = row[0], row[1]
        conn.close()
        return Result(True, data={"current_user": current_user, "roles": roles})
    except MySQLError as e:
        return failed(e)


def _rows(cur):
    cols = cur.column_names
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def read(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = _rows(cur)
    cur.close()
    return rows


def call(conn, name, args):
    """CALL a procedure. Returns (args with OUT values filled, result tables)."""
    cur = conn.cursor()
    out = cur.callproc(name, args)
    tables = []
    for result in cur.stored_results():
        cols = result.column_names
        tables.append([dict(zip(cols, r)) for r in result.fetchall()])
    conn.commit()
    cur.close()
    return list(out), tables


@contextlib.contextmanager
def user_conn(login):
    conn = connect(login["user"], login["password"])
    try:
        yield conn
    finally:
        conn.close()


@contextlib.contextmanager
def system_conn():
    conn = system_connect()
    try:
        yield conn
    finally:
        conn.close()


def system_read(sql, params=()):
    with system_conn() as conn:
        return read(conn, sql, params)


# ---------------------------------------------------------------------
# Drop-down lists (system connection)
# ---------------------------------------------------------------------
def participants(types=None):
    sql = ("SELECT participant_id, name, participant_type, city, license_status "
           "FROM participant")
    params = ()
    if types:
        sql += " WHERE participant_type IN (" + ",".join(["%s"] * len(types)) + ")"
        params = tuple(types)
    return system_read(sql + " ORDER BY participant_id", params)


def drugs():
    return system_read("SELECT drug_id, generic_name, brand_name, strength, dosage_form "
                       "FROM drug ORDER BY drug_id")


def lots_at(manufacturer_id):
    return system_read("SELECT lot_id, lot_no, material_name, received_date, coa_verified "
                       "FROM material_lot WHERE manufacturer_id = %s ORDER BY lot_id DESC",
                       (manufacturer_id,))


def partners_of(participant_id):
    """Who this participant can send to (its links), excluding CONSUMER."""
    return system_read("SELECT p.participant_id, p.name, p.participant_type, p.city "
                       "FROM link l JOIN participant p ON p.participant_id = l.to_participant "
                       "WHERE l.from_participant = %s AND p.participant_type <> 'CONSUMER' "
                       "ORDER BY p.participant_id", (participant_id,))


def incoming_shipments(participant_id):
    return system_read(
        "SELECT s.shipment_id, s.ship_time, f.participant_id AS from_id, f.name AS from_name, "
        "       COUNT(si.serial_no) AS packs "
        "FROM shipment s JOIN link l ON l.link_id = s.link_id "
        "JOIN participant f ON f.participant_id = l.from_participant "
        "JOIN shipment_item si ON si.shipment_id = s.shipment_id "
        "WHERE l.to_participant = %s AND s.status = 'DISPATCHED' "
        "GROUP BY s.shipment_id, s.ship_time, f.participant_id, f.name "
        "ORDER BY s.ship_time DESC LIMIT 200", (participant_id,))


def shipment_serials(shipment_id):
    return [r["serial_no"] for r in system_read(
        "SELECT serial_no FROM shipment_item WHERE shipment_id = %s ORDER BY serial_no",
        (shipment_id,))]


def batches_with_status(status, manufacturer_id=None):
    sql = ("SELECT b.batch_id, b.batch_no, b.manufacturer_id, p.name AS manufacturer, "
           "       d.brand_name, b.quantity, b.qc_status, b.mfg_date, b.expiry_date, "
           "       (SELECT COUNT(*) FROM pack k WHERE k.batch_id = b.batch_id) AS packs_made "
           "FROM batch b JOIN participant p ON p.participant_id = b.manufacturer_id "
           "JOIN drug d ON d.drug_id = b.drug_id WHERE b.qc_status = %s")
    params = [status]
    if manufacturer_id:
        sql += " AND b.manufacturer_id = %s"
        params.append(manufacturer_id)
    return system_read(sql + " ORDER BY b.batch_id DESC LIMIT 300", tuple(params))


def overview_counts():
    rows = system_read(
        "SELECT (SELECT COUNT(*) FROM participant) AS participants, "
        "       (SELECT COUNT(*) FROM batch) AS batches, "
        "       (SELECT COUNT(*) FROM pack) AS packs, "
        "       (SELECT COUNT(*) FROM shipment) AS shipments, "
        "       (SELECT COUNT(*) FROM trace_event) AS events, "
        "       (SELECT COUNT(*) FROM anomaly_flag WHERE resolved = FALSE) AS open_flags")
    return rows[0]


# ---------------------------------------------------------------------
# What the logged-in user can see (user connection)
# ---------------------------------------------------------------------
def my_batches(login, manufacturer_id):
    """A p_<id> login reads v_my_batches (MySQL filters by USER());
    admin / app read the batch table for the chosen manufacturer."""
    try:
        with user_conn(login) as conn:
            if login["account"]["participant"]:
                rows = read(conn, "SELECT * FROM v_my_batches ORDER BY batch_id DESC")
                source = "view v_my_batches (rows filtered by MySQL to this login)"
            else:
                rows = read(conn, "SELECT * FROM batch WHERE manufacturer_id = %s "
                                  "ORDER BY batch_id DESC", (manufacturer_id,))
                source = "table batch"
        return Result(True, data=rows, message=source)
    except MySQLError as e:
        return failed(e)


def my_stock(login, participant_id, status=None, limit=500):
    try:
        with user_conn(login) as conn:
            if login["account"]["participant"]:
                sql, params, source = "SELECT * FROM v_my_stock", [], "view v_my_stock (filtered by MySQL)"
                if status:
                    sql += " WHERE status = %s"
                    params.append(status)
            else:
                sql, params, source = "SELECT * FROM pack WHERE current_owner = %s", [participant_id], "table pack"
                if status:
                    sql += " AND status = %s"
                    params.append(status)
            rows = read(conn, sql + f" ORDER BY batch_id DESC, serial_no LIMIT {int(limit)}", tuple(params))
        return Result(True, data=rows, message=source)
    except MySQLError as e:
        return failed(e)


def open_flags(login, limit=500):
    try:
        with user_conn(login) as conn:
            try:
                rows = read(conn, f"SELECT * FROM v_open_flags ORDER BY flag_id DESC LIMIT {int(limit)}")
                source = "view v_open_flags"
            except MySQLError as e:
                if e.errno not in (1142,):
                    raise
                rows = read(conn, f"SELECT * FROM anomaly_flag WHERE resolved = FALSE "
                                  f"ORDER BY flag_id DESC LIMIT {int(limit)}")
                source = "table anomaly_flag (this account may not read the view)"
            summary = read(conn, "SELECT rule_code, severity, COUNT(*) AS flags FROM anomaly_flag "
                                 "WHERE resolved = FALSE GROUP BY rule_code, severity ORDER BY flags DESC")
        return Result(True, data=rows, message=source, tables=[("Open flags per rule", summary)])
    except MySQLError as e:
        return failed(e)


def link_stats(login, limit=25):
    try:
        with user_conn(login) as conn:
            rows = read(conn, "SELECT * FROM v_link_stats WHERE total_shipments > 0 "
                              f"ORDER BY open_flags DESC, mismatch_rate DESC LIMIT {int(limit)}")
        return Result(True, data=rows)
    except MySQLError as e:
        return failed(e)


# ---------------------------------------------------------------------
# Operations: stored procedures through the user connection
# ---------------------------------------------------------------------
def create_batch(login, drug_id, manufacturer_id, batch_no, mfg_date, expiry_date, quantity, lot_ids):
    try:
        with user_conn(login) as conn:
            out, _ = call(conn, "create_batch", [drug_id, manufacturer_id, batch_no, mfg_date,
                                                 expiry_date, quantity, ",".join(map(str, lot_ids)), 0])
            batch_id = out[7]
            row = read(conn, "SELECT batch_id, batch_no, quantity, qc_status, batch_hash FROM batch "
                             "WHERE batch_id = %s", (batch_id,)) if not login["account"]["participant"] else []
        return Result(True, f"Batch {batch_id} created as PENDING. Quality control must approve it "
                            f"before packs can be made.", data=batch_id,
                      tables=[("New batch", row)] if row else [])
    except MySQLError as e:
        return failed(e)


def approve_batch(login, batch_id):
    try:
        with user_conn(login) as conn:
            call(conn, "approve_batch", [batch_id])
        return Result(True, f"Batch {batch_id} is now APPROVED.")
    except MySQLError as e:
        return failed(e)


def generate_packs(login, batch_id):
    try:
        with user_conn(login) as conn:
            call(conn, "generate_packs", [batch_id])
        rows = system_read("SELECT serial_no, current_owner, status FROM pack WHERE batch_id = %s "
                           "ORDER BY serial_no LIMIT 50", (batch_id,))
        return Result(True, f"Packs generated for batch {batch_id}, each with a MANUFACTURED event and its hash.",
                      tables=[("New packs (first 50)", rows)])
    except MySQLError as e:
        return failed(e)


def dispatch(login, from_id, to_id, serials):
    try:
        with user_conn(login) as conn:
            out, _ = call(conn, "dispatch_shipment", [from_id, to_id, ",".join(serials), 0])
        return Result(True, f"Shipment {out[3]} dispatched with {len(serials)} pack(s). "
                            f"The packs are now IN_TRANSIT.", data=out[3])
    except MySQLError as e:
        return failed(e)


def receive(login, shipment_id, scanned):
    try:
        with user_conn(login) as conn:
            _, tables = call(conn, "receive_shipment", [shipment_id, ",".join(scanned)])
        summary = tables[0][0] if tables and tables[0] else {}
        flags = system_read("SELECT flag_id, rule_code, serial_no, severity FROM anomaly_flag "
                            "WHERE shipment_id = %s ORDER BY flag_id", (shipment_id,))
        msg = f"Shipment {shipment_id} recorded as {summary.get('status', '?')}."
        return Result(True, msg, data=summary,
                      tables=[("Result", tables[0] if tables else [])] +
                             ([("Flags raised for this shipment", flags)] if flags else []))
    except MySQLError as e:
        return failed(e)


def sell(login, retailer_id, serial):
    try:
        with user_conn(login) as conn:
            out, _ = call(conn, "sell_pack", [retailer_id, serial, ""])
        result = out[2]
        if result == "REFUSED_ALREADY_SOLD":
            flags = system_read("SELECT flag_id, rule_code, serial_no, severity, detected_at "
                                "FROM anomaly_flag WHERE serial_no = %s AND rule_code = 'SOLD_TWICE' "
                                "ORDER BY flag_id DESC LIMIT 3", (serial,))
            return Result(False, error={
                "kind": "rule", "title": "Refused by a database rule: already sold",
                "detail": "This serial was already sold once, so this pack is probably a copy (cloned code). "
                          "Nothing was sold and a SOLD_TWICE flag was saved for investigation.",
                "enforced_by": "stored procedure sell_pack", "raw": f"sell_pack returned {result}"},
                tables=[("Flag saved", flags)])
        return Result(True, f"Pack {serial} sold. Its status is now SOLD.")
    except MySQLError as e:
        return failed(e)


def recall(login, batch_id):
    try:
        with user_conn(login) as conn:
            _, tables = call(conn, "recall_batch", [batch_id])
        return Result(True, f"Batch {batch_id} recalled. Every unsold pack is now RECALLED.",
                      tables=[("Everyone the batch reached (recursive query)", tables[0] if tables else [])])
    except MySQLError as e:
        return failed(e)


def set_license(login, participant_id, status):
    try:
        with user_conn(login) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE participant SET license_status = %s WHERE participant_id = %s",
                        (status, participant_id))
            changed = cur.rowcount
            conn.commit()
            cur.close()
        hist = system_read("SELECT * FROM license_history WHERE participant_id = %s "
                           "ORDER BY history_id DESC LIMIT 5", (participant_id,))
        if not changed:
            return Result(True, "Nothing changed: the licence already had this status.",
                          tables=[("Licence history (newest first)", hist)])
        return Result(True, f"Licence of participant {participant_id} is now {status}. "
                            f"The history row below was written automatically by a trigger.",
                      tables=[("Licence history (newest first)", hist)])
    except MySQLError as e:
        return failed(e)


def run_detection(login):
    try:
        before = system_read("SELECT COUNT(*) AS n FROM anomaly_flag")[0]["n"]
        with user_conn(login) as conn:
            call(conn, "run_detection", [])
        after = system_read("SELECT COUNT(*) AS n FROM anomaly_flag")[0]["n"]
        per_rule = system_read("SELECT rule_code, COUNT(*) AS flags FROM anomaly_flag "
                               "GROUP BY rule_code ORDER BY flags DESC")
        return Result(True, f"Detection finished: {after - before} new flag(s). Running it again adds none.",
                      tables=[("All flags per rule", per_rule)])
    except MySQLError as e:
        return failed(e)


def evaluation_summary(login):
    """How many planted counterfeits the flags caught, per scenario (like 07_evaluation.sql).
    Runs as the logged-in account: only admin may read the answer key."""
    scenario_rules = {
        "FAKE_MATERIAL": ("lot", ("LOT_COA_NOT_VERIFIED", "LOT_OVERWEIGHT", "SUPPLIER_UNLICENSED")),
        "TRANSIT_SWAP": ("serial", ("UNKNOWN_SERIAL", "MISSING_PACK")),
        "INVENTED_SERIAL": ("serial", ("UNKNOWN_SERIAL",)),
        "CLONED_SERIAL": ("serial", ("SOLD_TWICE",)),
        "UNLICENSED_HANDLER": ("serial", ("HANDLER_UNLICENSED",)),
        "STAGE_SKIPPED": ("serial", ("STAGE_SKIPPED",)),
    }
    out = []
    try:
        conn = connect(login["user"], login["password"])
    except MySQLError as e:
        return failed(e)
    try:
        for scenario, (key, rules) in scenario_rules.items():
            col = "lot_id" if key == "lot" else "serial_no"
            marks = ",".join(["%s"] * len(rules))
            injected = {r[col] for r in read(conn, f"SELECT DISTINCT {col} FROM injected_counterfeit "
                                                   f"WHERE scenario_type = %s AND {col} IS NOT NULL", (scenario,))}
            flagged = {r[col] for r in read(conn, f"SELECT DISTINCT {col} FROM anomaly_flag "
                                                  f"WHERE rule_code IN ({marks}) AND {col} IS NOT NULL", rules)}
            caught = len(injected & flagged)
            out.append({"scenario": scenario, "rules": ", ".join(rules), "planted": len(injected),
                        "caught": caught, "missed": len(injected - flagged),
                        "recall_%": round(100 * caught / len(injected), 1) if injected else None})
    except MySQLError as e:
        return failed(e)
    finally:
        conn.close()
    return Result(True, data=out)


# ---------------------------------------------------------------------
# Verification, ledger and tamper demo (her modules, system account)
# ---------------------------------------------------------------------
CITY_COORDS = {
    "Mumbai": (19.0760, 72.8777), "Pune": (18.5204, 73.8567), "Delhi": (28.6139, 77.2090),
    "Bengaluru": (12.9716, 77.5946), "Chennai": (13.0827, 80.2707), "Hyderabad": (17.3850, 78.4867),
    "Kolkata": (22.5726, 88.3639), "Ahmedabad": (23.0225, 72.5714), "Jaipur": (26.9124, 75.7873),
    "Lucknow": (26.8467, 80.9462), "Bhopal": (23.2599, 77.4126), "Kochi": (9.9312, 76.2673),
}


def captured(fn, *args, **kwargs):
    """Run one of her scripts' functions and keep what it prints."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        value = fn(*args, **kwargs)
    return value, buf.getvalue()


def verify_serial(serial, gtin=None, batch_no=None, expiry=None, city=None):
    from ledger.verify import verify
    lat, lon = CITY_COORDS.get(city, (None, None)) if city else (None, None)
    try:
        result = verify(serial_no=serial, qr_gtin=gtin or None, qr_batch_no=batch_no or None,
                        qr_expiry=expiry or None, city=city or None, lat=lat, lon=lon)
        return Result(True, data=result)
    except MySQLError as e:
        return failed(e)


def ledger_status():
    from common.config import get_mongo_db
    col = get_mongo_db()["ledger_blocks"]
    last = col.find_one(sort=[("block_index", -1)], projection={"_id": 0, "items": 0})
    per_type = list(col.aggregate([{"$group": {"_id": "$block_type", "blocks": {"$sum": 1}}},
                                   {"$sort": {"_id": 1}}]))
    unsealed = system_read(
        "SELECT (SELECT COUNT(*) FROM material_lot WHERE ledger_synced = FALSE) AS lots, "
        "       (SELECT COUNT(*) FROM batch WHERE ledger_synced = FALSE) AS batches, "
        "       (SELECT COUNT(*) FROM trace_event WHERE ledger_synced = FALSE) AS events")[0]
    return {"blocks": col.count_documents({}), "last": last, "unsealed": unsealed,
            "per_type": [{"block_type": r["_id"], "blocks": r["blocks"]} for r in per_type],
            "scans": get_mongo_db()["scan_logs"].count_documents({})}


def seal_ledger():
    from ledger import ledger_writer
    try:
        _, log = captured(ledger_writer.run)
        return Result(True, "New records sealed into the ledger.", log=log)
    except MySQLError as e:
        return failed(e)


def reconcile():
    from ledger.reconcile import run_reconciliation
    try:
        findings, log = captured(run_reconciliation)
        counts = {t: sum(f["type"] == t for f in findings)
                  for t in ("LEDGER_MISSING", "HASH_MISMATCH", "CHAIN_BROKEN")}
        rows = [{"type": f["type"], "record": f"{f.get('kind', 'block')} {f.get('id', f.get('block_index', ''))}",
                 "message": f["message"]} for f in findings]
        return Result(True, data=counts, tables=[("Findings", rows)], log=log)
    except MySQLError as e:
        return failed(e)


def _jsonable(d):
    return {k: (str(v) if isinstance(v, (datetime, date, Decimal)) else v) for k, v in d.items()}


def tamper_state():
    if TAMPER_BACKUP.exists():
        return json.loads(TAMPER_BACKUP.read_text())
    return {}


def tamper_try_without_switch(login):
    """Step 1: edit a sealed event as the logged-in user, without the switch."""
    try:
        with user_conn(login) as conn:
            cur = conn.cursor()
            cur.execute("SELECT event_id FROM trace_event WHERE ledger_synced = TRUE ORDER BY event_id LIMIT 1")
            row = cur.fetchone()
            event_id = row[0] if row else 1
            cur.execute("UPDATE trace_event SET event_time = DATE_ADD(event_time, INTERVAL 1 SECOND) "
                        "WHERE event_id = %s", (event_id,))
            conn.rollback()
        return Result(False, error={"kind": "other", "title": "WARNING: the edit was accepted",
                                    "detail": "The append-only trigger did not stop it. Is 02_triggers.sql installed?",
                                    "enforced_by": "-", "raw": ""})
    except MySQLError as e:
        return failed(e)


def tamper_records(login):
    """Step 2: as an insider (switch on), change one event, one lot and one batch."""
    from ledger import tamper_demo
    state = tamper_state()
    if state.get("sql"):
        return Result(False, error={"kind": "other", "title": "Already tampered",
                                    "detail": "Restore the original values first (step 4).",
                                    "enforced_by": "-", "raw": ""})
    try:
        with system_conn() as sconn:
            scur = sconn.cursor(dictionary=True)
            event, lot, batch = tamper_demo.get_demo_records(scur)
        with user_conn(login) as conn:
            cur = conn.cursor(dictionary=True)
            _, log = captured(tamper_demo.tamper_records, cur, event, lot, batch)
            conn.commit()
            cur.execute("SET @tamper_demo = NULL")
        state["sql"] = {"event": _jsonable(event), "lot": _jsonable(lot), "batch": _jsonable(batch)}
        TAMPER_BACKUP.write_text(json.dumps(state, indent=1))
        return Result(True, f"Changed event {event['event_id']} (time +1 day), lot {lot['lot_id']} "
                            f"(+1 kg received) and batch {batch['batch_id']} (expiry +1 day). "
                            f"Original values saved in gui/tamper_backup.json.", log=log)
    except MySQLError as e:
        return failed(e)


def restore_records(login):
    """Step 4: put the original values back (needs the switch again)."""
    from ledger import tamper_demo
    state = tamper_state()
    if not state.get("sql"):
        return Result(True, "Nothing to restore: no record is currently tampered.")
    s = state["sql"]
    try:
        with user_conn(login) as conn:
            cur = conn.cursor(dictionary=True)
            cur.execute("SET @tamper_demo = 1")
            _, log = captured(tamper_demo.restore_records, cur, s["event"], s["lot"], s["batch"])
            conn.commit()
        del state["sql"]
        if state:
            TAMPER_BACKUP.write_text(json.dumps(state, indent=1))
        elif TAMPER_BACKUP.exists():
            TAMPER_BACKUP.unlink()
        return Result(True, "Original event, lot and batch values restored.", log=log)
    except MySQLError as e:
        return failed(e)


def tamper_block():
    """Edit the first ledger block directly in MongoDB (breaks the chain)."""
    from common.config import get_mongo_db
    state = tamper_state()
    if state.get("block"):
        return Result(False, error={"kind": "other", "title": "Block already edited",
                                    "detail": "Restore the block first.", "enforced_by": "-", "raw": ""})
    col = get_mongo_db()["ledger_blocks"]
    block = col.find_one({"block_index": 0})
    if not block:
        return Result(False, error={"kind": "other", "title": "Ledger is empty",
                                    "detail": "Seal the records first.", "enforced_by": "-", "raw": ""})
    original = block["items"][0]["hash"]
    state["block"] = {"block_index": 0, "hash": original}
    TAMPER_BACKUP.write_text(json.dumps(state, indent=1))
    col.update_one({"block_index": 0}, {"$set": {"items.0.hash": "f" * 64}})
    return Result(True, "Block 0 in MongoDB now carries a different item hash (as if someone edited the ledger).")


def restore_block():
    from common.config import get_mongo_db
    state = tamper_state()
    if not state.get("block"):
        return Result(True, "Nothing to restore: the ledger blocks are untouched.")
    get_mongo_db()["ledger_blocks"].update_one({"block_index": state["block"]["block_index"]},
                                               {"$set": {"items.0.hash": state["block"]["hash"]}})
    del state["block"]
    if state:
        TAMPER_BACKUP.write_text(json.dumps(state, indent=1))
    elif TAMPER_BACKUP.exists():
        TAMPER_BACKUP.unlink()
    return Result(True, "Block 0 restored to its original hash.")


# ---------------------------------------------------------------------
# Security lab: try protected actions, then always ROLLBACK
# ---------------------------------------------------------------------
def security_attempts():
    """The list of attempts. Each runs as the logged-in account; nothing is kept."""
    m2_partner = system_read("SELECT to_participant FROM link WHERE from_participant = 6 ORDER BY link_id LIMIT 1")
    m2_dist = m2_partner[0]["to_participant"] if m2_partner else 0
    return [
        ("A1", "Read the counterfeit answer key", "query",
         "SELECT COUNT(*) AS n FROM injected_counterfeit", ()),
        ("A2", "Read manufacturer M2's batches (table batch)", "query",
         "SELECT COUNT(*) AS n FROM batch WHERE manufacturer_id = 6", ()),
        ("A3", "Read 'my batches' through view v_my_batches", "query",
         "SELECT COUNT(*) AS n FROM v_my_batches", ()),
        ("A4", "Read retailer R2's stock (table pack)", "query",
         "SELECT COUNT(*) AS n FROM pack WHERE current_owner = 24", ()),
        ("A5", "Read 'my stock' through view v_my_stock", "query",
         "SELECT COUNT(*) AS n FROM v_my_stock", ()),
        ("A6", "Insert a batch directly, skipping create_batch", "exec",
         "INSERT INTO batch (drug_id, manufacturer_id, batch_no, mfg_date, expiry_date, quantity) "
         "VALUES (1, 5, 'SECLAB-TEST', CURDATE(), DATE_ADD(CURDATE(), INTERVAL 2 YEAR), 1)", ()),
        ("A7", "Edit a supply-chain history event", "exec",
         "UPDATE trace_event SET event_time = DATE_ADD(event_time, INTERVAL 1 SECOND) WHERE event_id = 1", ()),
        ("A8", "Delete a supply-chain history event", "exec",
         "DELETE FROM trace_event WHERE event_id = 1", ()),
        ("A9", "Delete a shipment", "exec",
         "DELETE FROM shipment WHERE shipment_id = 1", ()),
        ("A10", "Change an event's type (column the ledger may not touch)", "exec",
         "UPDATE trace_event SET event_type = 'SOLD' WHERE event_id = 1", ()),
        ("A11", "Mark an event as sealed (the ledger's one allowed change)", "exec",
         "UPDATE trace_event SET ledger_synced = TRUE WHERE event_id = 1", ()),
        ("A12", "Approve a batch (quality control)", "proc", "approve_batch", [1]),
        ("A13", "Dispatch packs pretending to be manufacturer M2", "proc",
         "dispatch_shipment", [6, m2_dist, "NOSUCHSERIAL1", 0]),
        ("A14", "Add a detection flag", "exec",
         "INSERT INTO anomaly_flag (rule_code, severity, detected_at) VALUES ('SECURITY_LAB_TEST', 'LOW', NOW())", ()),
        ("A15", "Read MySQL's own user and password table", "query",
         "SELECT COUNT(*) AS n FROM mysql.user", ()),
    ]


def run_attempts(user, password, attempts=None):
    """Returns one row per attempt: verdict ALLOWED / BLOCKED / REFUSED and the detail."""
    attempts = attempts or security_attempts()
    try:
        conn = connect(user, password)
    except MySQLError as e:
        info = explain(e)
        return [{"#": a[0], "attempt": a[1], "result": "LOGIN FAILED", "detail": info["detail"]} for a in attempts]
    rows = []
    try:
        for code, title, kind, stmt, params in attempts:
            try:
                cur = conn.cursor()
                if kind == "query":
                    cur.execute(stmt, params)
                    value = cur.fetchone()[0]
                    detail = f"returned {value}"
                elif kind == "exec":
                    cur.execute(stmt, params)
                    detail = f"would change {cur.rowcount} row(s); undone with ROLLBACK"
                else:
                    cur.callproc(stmt, params)
                    detail = "ran; undone with ROLLBACK"
                cur.close()
                verdict = "ALLOWED"
            except MySQLError as e:
                info = explain(e)
                verdict = short_verdict(info)
                detail = info["raw"]
            finally:
                try:
                    conn.rollback()
                except MySQLError:
                    pass
            rows.append({"#": code, "attempt": title, "result": verdict, "detail": detail})
    finally:
        conn.close()
    return rows


# ---------------------------------------------------------------------
# Demo helper: handy IDs and serials (admin reads the answer key)
# ---------------------------------------------------------------------
def demo_samples():
    q = system_read
    out = []

    def add(label, rows, col="serial_no", note=""):
        if rows:
            out.append({"use for": label, "value": rows[0][col], "note": note})

    add("Verify: genuine pack", q(
        "SELECT p.serial_no FROM pack p WHERE p.status = 'SOLD' AND NOT EXISTS "
        "(SELECT 1 FROM injected_counterfeit i WHERE i.serial_no = p.serial_no) "
        "AND NOT EXISTS (SELECT 1 FROM anomaly_flag f WHERE f.serial_no = p.serial_no) "
        "ORDER BY p.serial_no LIMIT 1"), note="sold normally, never flagged")
    add("Verify: cloned code", q(
        "SELECT serial_no FROM injected_counterfeit WHERE scenario_type = 'CLONED_SERIAL' ORDER BY inject_id LIMIT 1"),
        note="sold twice in two cities")
    add("Verify: invented serial", q(
        "SELECT i.serial_no FROM injected_counterfeit i WHERE i.scenario_type = 'INVENTED_SERIAL' "
        "AND NOT EXISTS (SELECT 1 FROM pack p WHERE p.serial_no = i.serial_no) ORDER BY i.inject_id LIMIT 1"),
        note="never made by any factory")
    add("Verify: skipped a stage", q(
        "SELECT serial_no FROM injected_counterfeit WHERE scenario_type = 'STAGE_SKIPPED' ORDER BY inject_id LIMIT 1"))
    add("Verify: unlicensed handler", q(
        "SELECT serial_no FROM injected_counterfeit WHERE scenario_type = 'UNLICENSED_HANDLER' "
        "ORDER BY inject_id LIMIT 1"))
    add("Sell at R1: pack in stock", q(
        "SELECT serial_no FROM pack WHERE current_owner = 23 AND status = 'IN_STOCK' ORDER BY serial_no LIMIT 1"))
    add("Sell at R1: already sold (clone test)", q(
        "SELECT e.serial_no FROM trace_event e JOIN shipment s ON s.shipment_id = e.shipment_id "
        "JOIN link l ON l.link_id = s.link_id WHERE l.from_participant = 23 AND e.event_type = 'SOLD' "
        "ORDER BY e.event_id LIMIT 1"))
    add("Sell at R1: someone else's pack", q(
        "SELECT serial_no FROM pack WHERE current_owner = 24 AND status = 'IN_STOCK' ORDER BY serial_no LIMIT 1"),
        note="owned by R2, so NOT_OWNER")
    route = q("SELECT l1.to_participant AS d FROM link l1 JOIN link l2 ON l2.from_participant = l1.to_participant "
              "WHERE l1.from_participant = 5 AND l2.to_participant = 23 LIMIT 1")
    if route:
        out.append({"use for": "Flow M1 -> distributor -> R1", "value": str(route[0]["d"]),
                    "note": "a distributor linked to both M1 and R1"})
    else:
        d = q("SELECT to_participant AS d FROM link WHERE from_participant = 5 ORDER BY link_id LIMIT 1")
        if d:
            out.append({"use for": "Flow M1 -> distributor", "value": str(d[0]["d"]),
                        "note": "no distributor serves both M1 and R1; use this one, then any of its retailers"})
    return out
