"""
Pages that check things: pack verification, detection, ledger integrity,
the security lab, and a demo helper with ready-made test values.
"""

import pandas as pd
import streamlit as st

from gui import services, settings, ui, validation

VERDICT_STYLE = {"GENUINE": ("success", "✅"), "SUSPICIOUS": ("warning", "⚠️"), "FAKE": ("error", "❌")}


# ---------------------------------------------------------------------
# Verify a pack (consumer, no login needed)
# ---------------------------------------------------------------------
def verify_page():
    st.header("Verify a pack")
    st.write("A customer types the serial number printed under the QR code. The system checks the "
             "database and the ledger and answers GENUINE, SUSPICIOUS or FAKE.")
    ui.who_can_use("Anyone, no login needed (consumers have no account). Runs ledger/verify.py.")
    key = "verify"
    labels = {"serial": "Serial number", "gtin": "GTIN", "batch_no": "Batch number", "expiry": "Expiry date"}
    errors = ui.form_errors(key)
    ui.error_summary(errors, labels)
    st.caption("Fields marked * are required.")
    with st.form(key):
        st.markdown("**1. The pack**")
        serial = st.text_input("Serial number *", key=f"{key}_serial", placeholder="e.g. FK38QD9S4VXK")
        ui.hint("4 to 20 capital letters or digits, as printed under the QR code.")
        ui.field_error(errors, "serial")
        st.markdown("**2. What the QR code says (optional)**")
        c1, c2, c3 = st.columns(3)
        with c1:
            gtin = st.text_input("GTIN (optional)", key=f"{key}_gtin", placeholder="13 digits")
            ui.field_error(errors, "gtin")
        with c2:
            batch_no = st.text_input("Batch number (optional)", key=f"{key}_batch", placeholder="e.g. VL2601-001")
            ui.field_error(errors, "batch_no")
        with c3:
            expiry = st.text_input("Expiry date (optional)", key=f"{key}_expiry", placeholder="YYYY-MM-DD")
            ui.field_error(errors, "expiry")
        ui.hint("If given, each one must match the database; a relabelled pack fails here.")
        st.markdown("**3. Where you are (optional)**")
        city = st.selectbox("City (optional)", ["(not given)"] + sorted(services.CITY_COORDS), key=f"{key}_city")
        ui.hint("Used to spot the same code being scanned in two distant cities.")
        submitted = st.form_submit_button("Check this pack", type="primary")
    if submitted:
        s = serial.strip().upper() if ui.checks_on() else serial
        g, b, x = gtin.strip(), batch_no.strip().upper(), expiry.strip()
        errors = validation.check_verify(s, g, b, x) if ui.checks_on() else {}
        c = None if city == "(not given)" else city
        ui.handle_submit(key, errors, lambda: services.verify_serial(s, g, b, x, c))

    res = st.session_state.get(f"{key}__result")
    if res is None:
        return
    if not res.ok:
        ui.show_result(res)
        return
    r = res.data
    kind, icon = VERDICT_STYLE.get(r["verdict"], ("info", ""))
    getattr(st, kind)(f"## {icon} {r['verdict']}\nSerial **{r['serial_no']}**")
    if r["reasons"]:
        st.markdown("**Why:**\n" + "\n".join(f"- {reason}" for reason in r["reasons"]))
    else:
        st.markdown("Registered at a factory, every handover is recorded and licensed, every hash "
                    "matches the ledger, and the scan history is normal.")
    if r["route"]:
        st.markdown("**Journey of this pack** (view v_serial_journey)")
        ui.table([{k: v for k, v in step.items() if k in
                   ("event_time", "event_type", "sender_name", "sender_city", "receiver_name",
                    "receiver_city", "shipment_id", "event_id")} for step in r["route"]])
    if not r["serial_no"].isalnum():
        st.caption("The text was sent to MySQL as a value, never as part of the SQL, so even an "
                   "injection string is only looked up as an unknown serial.")


# ---------------------------------------------------------------------
# Detection and flags
# ---------------------------------------------------------------------
def detection_page():
    st.header("Counterfeit detection")
    st.write("Detection rules (sql/06_detection.sql) read the real records, never the answer key, and "
             "write each finding into anomaly_flag.")
    ui.who_can_use("Run: admin. Read flags: admin, readonly (view), detection (table). "
                   "Accuracy check: admin only, because it reads the answer key.")
    tab_run, tab_flags, tab_links, tab_eval = st.tabs(
        ["Run detection", "Open flags", "Riskiest links", "How accurate is it?"])
    with tab_run:
        st.write("Runs every rule once. Already-flagged findings are skipped, so a second run adds nothing.")
        if st.button("Run detection now", type="primary", key="run_det"):
            ui.handle_submit("detect", {}, lambda: services.run_detection(ui.login()))
        ui.stored_result("detect")
    with tab_flags:
        res = services.open_flags(ui.login())
        if res.ok:
            st.caption(f"Read from {res.message}.")
            ui.show_result(services.Result(True, tables=res.tables))
            st.markdown("**Newest 500 open flags**")
            ui.table(res.data, height=380)
        else:
            ui.show_error(res.error)
    with tab_links:
        res = services.link_stats(ui.login())
        if res.ok:
            st.caption("From view v_link_stats: trading links with the most open flags and missing packs.")
            ui.table(res.data)
        else:
            ui.show_error(res.error)
    with tab_eval:
        st.write("Compares the flags with the planted counterfeits (injected_counterfeit). "
                 "Try it as the detection login: MySQL refuses it the answer key.")
        if st.button("Check accuracy", key="eval_btn"):
            ui.handle_submit("eval", {}, lambda: services.evaluation_summary(ui.login()))
        res = st.session_state.get("eval__result")
        if res is not None:
            if res.ok:
                ui.table(res.data)
            else:
                ui.show_result(res)


# ---------------------------------------------------------------------
# Ledger integrity and the tamper demo
# ---------------------------------------------------------------------
def ledger_page():
    st.header("Ledger integrity")
    st.write("Every lot, batch and event is sealed into a hash chain in MongoDB. Recomputing the hashes "
             "from MySQL and comparing them with the chain shows whether anyone changed history.")
    ui.who_can_use("Status and integrity check: any login. Tamper demo: only admin can edit records "
                   "(and only with the tamper switch); other logins are refused by MySQL.")
    try:
        status = services.ledger_status()
    except Exception as e:
        ui.show_result(ui.crash_result(e))
        return
    c = st.columns(5)
    c[0].metric("Blocks in the chain", status["blocks"])
    c[1].metric("Unsealed lots", status["unsealed"]["lots"])
    c[2].metric("Unsealed batches", status["unsealed"]["batches"])
    c[3].metric("Unsealed events", status["unsealed"]["events"])
    c[4].metric("Consumer scans", status["scans"])
    if status["last"]:
        st.caption(f"Last block: #{status['last']['block_index']} ({status['last']['block_type']}), "
                   f"hash {status['last']['block_hash'][:16]}…")
    with st.expander("Blocks per type"):
        ui.table(status["per_type"])

    st.subheader("1. Seal new records")
    st.write("Runs ledger/ledger_writer.py: everything not yet sealed (for example a batch made in this "
             "GUI) is added to the chain. Do this before checking integrity.")
    if st.button("Seal new records", key="seal_btn"):
        ui.handle_submit("seal", {}, services.seal_ledger)
    ui.stored_result("seal")

    st.subheader("2. Check integrity")
    st.write("Runs ledger/reconcile.py: recomputes every hash from MySQL and walks the whole chain.")
    if st.button("Check integrity now", type="primary", key="rec_btn"):
        ui.handle_submit("reconcile", {}, services.reconcile)
    show_reconcile("reconcile")

    st.subheader("3. Tamper demo (an insider edits the database)")
    state = services.tamper_state()
    if state:
        st.warning("Records are currently TAMPERED: " + ", ".join(state) + ". Restore them before you finish.")
    steps = [
        ("t1", "Step 1 · Try to edit history normally",
         "Changes a sealed event's time by one second. The append-only trigger must refuse it, even for admin.",
         lambda: services.tamper_try_without_switch(ui.login())),
        ("t2", "Step 2 · Tamper as an insider",
         "Turns on the tamper switch and changes one event's time, one lot's weight and one batch's expiry date.",
         lambda: services.tamper_records(ui.login())),
        ("t3", "Step 3 · Check integrity",
         "Reconciliation must now name the exact event, lot and batch that were changed.",
         services.reconcile),
        ("t4", "Step 4 · Restore the original values", "Puts the saved original values back.",
         lambda: services.restore_records(ui.login())),
        ("t5", "Step 5 · Check integrity again", "Everything must match again.", services.reconcile),
    ]
    for key, title, text, action in steps:
        with st.container():
            st.markdown(f"**{title}**  \n{text}")
            if st.button(title.split("·")[1].strip(), key=f"{key}_btn"):
                ui.handle_submit(key, {}, action)
            if key in ("t3", "t5"):
                show_reconcile(key)
            else:
                ui.stored_result(key)

    st.markdown("**Optional · Edit the ledger itself (MongoDB)**  \nChanges one hash inside block 0. "
                "The chain check then fails from that block on. Restore it afterwards.")
    b1, b2 = st.columns(2)
    with b1:
        if st.button("Edit block 0", key="tb_btn"):
            ui.handle_submit("tb", {}, services.tamper_block)
        ui.stored_result("tb")
    with b2:
        if st.button("Restore block 0", key="rb_btn"):
            ui.handle_submit("rb", {}, services.restore_block)
        ui.stored_result("rb")


def show_reconcile(key):
    res = st.session_state.get(f"{key}__result")
    if res is None:
        return
    if not res.ok:
        ui.show_result(res)
        return
    counts = res.data
    if not isinstance(counts, dict) or "HASH_MISMATCH" not in counts:
        ui.show_result(res)
        return
    total = sum(counts.values())
    if total == 0:
        st.success("✅ Ledger intact: LEDGER_MISSING 0 · HASH_MISMATCH 0 · CHAIN_BROKEN 0")
    else:
        st.error(f"❌ Integrity problems found: LEDGER_MISSING {counts['LEDGER_MISSING']} · "
                 f"HASH_MISMATCH {counts['HASH_MISMATCH']} · CHAIN_BROKEN {counts['CHAIN_BROKEN']}")
        rows = res.tables[0][1] if res.tables else []
        ui.table(rows[:200])
        if counts["LEDGER_MISSING"] and not counts["HASH_MISMATCH"]:
            st.caption("Only LEDGER_MISSING: new records are not sealed yet. Press 'Seal new records'.")


# ---------------------------------------------------------------------
# Security lab
# ---------------------------------------------------------------------
RESULT_ICON = {"ALLOWED": "✅ ALLOWED", "BLOCKED": "⛔ BLOCKED", "REFUSED": "🛑 REFUSED",
               "ERROR": "⚠️ ERROR", "LOGIN FAILED": "🔒 LOGIN FAILED"}


def security_page():
    st.header("Security lab")
    st.write("Each button below really sends the statement to MySQL as the account you are logged in "
             "with. Nothing is hidden in the GUI: MySQL decides. Every attempt is undone afterwards "
             "(ROLLBACK), so nothing is changed.")
    st.markdown("- **⛔ BLOCKED**: this account has no permission (MySQL privileges, sql/05_roles.sql)\n"
                "- **🛑 REFUSED**: permission is there, but a trigger, procedure or table rule said no\n"
                "- **✅ ALLOWED**: MySQL accepted it (then it was rolled back)")
    lg = ui.login()
    st.info(f"Logged in as **{lg['user']}**: {lg['account']['who']}")
    attempts = services.security_attempts()
    with st.expander("What each attempt sends to MySQL"):
        ui.table([{"#": a[0], "attempt": a[1], "statement": a[3] if a[2] != "proc" else
                   f"CALL {a[3]}({', '.join(map(str, a[4]))})"} for a in attempts])

    if st.button(f"Run all {len(attempts)} attempts as {lg['user']}", type="primary", key="lab_btn"):
        st.session_state["lab_rows"] = services.run_attempts(lg["user"], lg["password"], attempts)
    rows = st.session_state.get("lab_rows")
    if rows:
        ui.table([{**r, "result": RESULT_ICON.get(r["result"], r["result"])} for r in rows], height=560)

    st.subheader("Compare all accounts")
    st.write("Runs the same attempts for all seven demo accounts, using the passwords in .env.")
    if st.button("Compare all accounts", key="cmp_btn"):
        matrix = {}
        with st.spinner("Logging in as each account..."):
            for acc in settings.ACCOUNTS:
                pw = settings.account_password_from_env(acc)
                result = (services.run_attempts(acc["user"], pw, attempts) if pw else
                          [{"#": a[0], "attempt": a[1], "result": "LOGIN FAILED"} for a in attempts])
                matrix[acc["user"]] = {r["#"]: RESULT_ICON.get(r["result"], r["result"]) for r in result}
        st.session_state["lab_matrix"] = matrix
    matrix = st.session_state.get("lab_matrix")
    if matrix:
        df = pd.DataFrame(matrix)
        df.insert(0, "attempt", [a[1] for a in attempts])
        df.index.name = "#"
        st.dataframe(df, height=600)


# ---------------------------------------------------------------------
# Demo helper
# ---------------------------------------------------------------------
def demo_page():
    st.header("Demo helper")
    st.write("Ready-made values for the live demo, read from the answer key (so only for the presenter).")
    ui.who_can_use("Admin only; it reads injected_counterfeit through the system account.")
    if ui.login()["account"]["role"] != "role_admin":
        ui.show_error({"kind": "denied", "title": "Access denied", "detail":
                       "Only the administrator may see the answer key.",
                       "enforced_by": "this page (the answer key itself is also protected by MySQL: see "
                                      "Security lab, attempt A1)", "raw": ""})
        return
    try:
        ui.table(services.demo_samples())
    except Exception as e:
        ui.show_result(ui.crash_result(e))
    st.markdown("""
**A full run through, in order**
1. *Batches* as **p_5**: register a batch (it is PENDING).
2. Try *Make packs* as p_5: refused, BATCH_NOT_APPROVED.
3. *Quality control* as **admin** (or **app**): approve it. (As p_5 MySQL refuses: no permission.)
4. *Batches* as **p_5**: make the packs.
5. *Shipments* as **p_5**: dispatch some packs to the distributor in the table above.
6. *Shipments* as **app**, acting for that distributor: receive them, marking one missing and adding a fake serial.
7. *Detection* as **admin**: see the MISSING_PACK and UNKNOWN_SERIAL flags.
8. *Ledger integrity*: seal the new records, check integrity, then run the tamper demo.
9. *Verify a pack*: the genuine, cloned and invented serials above give three different verdicts.
""")
