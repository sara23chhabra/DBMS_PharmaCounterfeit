"""
Pages for the supply-chain operations. Each form:
  1. checks its fields (gui/validation.py) when "form checks" are on,
  2. calls one stored procedure through the logged-in MySQL account,
  3. shows the result, or the refusal explained in plain words.
"""

from datetime import date, timedelta

import streamlit as st

from gui import services, ui, validation


# ---------------------------------------------------------------------
# Batches (manufacturer)
# ---------------------------------------------------------------------
BATCH_LABELS = {"batch_no": "Batch number", "mfg_date": "Manufacturing date", "expiry_date": "Expiry date",
                "quantity": "Number of packs", "lots": "Raw-material lots", "extra_lots": "Other lot IDs"}


def batches_page():
    st.header("Batches")
    st.write("A manufacturer registers a production run, quality control approves it, "
             "then the manufacturer makes the packs.")
    ui.who_can_use("Manufacturer M1 (p_5), and admin / app acting for any manufacturer. "
                   "Any other login is refused by MySQL, even if it opens this page.")
    pid = ui.choose_actor(["MANUFACTURER"], "Manufacturer *", "bat_actor")
    if not pid:
        return
    tab_list, tab_new, tab_packs = st.tabs(["My batches", "Register a batch", "Make packs"])
    with tab_list:
        res = services.my_batches(ui.login(), pid)
        if res.ok:
            st.caption(f"{len(res.data)} batch(es), read from {res.message}.")
            ui.table(res.data, height=380)
        else:
            ui.show_error(res.error)
    with tab_new:
        create_batch_form(pid)
    with tab_packs:
        generate_packs_form(pid, res.data if res.ok else [])


def drug_label(d):
    return f"{d['brand_name']} ({d['generic_name']} {d['strength']}, {d['dosage_form'].lower()})"


def lot_label(lot):
    text = f"Lot {lot['lot_id']} · {lot['material_name']} · {lot['lot_no']}"
    return text if lot["coa_verified"] else text + " · certificate NOT verified"


def create_batch_form(pid):
    key = "create_batch"
    errors = ui.form_errors(key)
    ui.error_summary(errors, BATCH_LABELS)
    drug_list = services.drugs()
    lot_list = services.lots_at(pid)
    st.caption("Fields marked * are required.")
    with st.form(key):
        st.markdown("**1. Medicine**")
        drug = st.selectbox("Medicine *", drug_list, format_func=drug_label, key=f"{key}_drug")

        st.markdown("**2. Batch details**")
        batch_no = st.text_input("Batch number *", key=f"{key}_no", placeholder="e.g. VL2611-101")
        ui.hint("3 to 30 capital letters, digits or hyphens. Must not be used before by this factory.")
        ui.field_error(errors, "batch_no")
        c1, c2 = st.columns(2)
        with c1:
            mfg = st.date_input("Manufacturing date *", value=date.today(), key=f"{key}_mfg")
            ui.field_error(errors, "mfg_date")
        with c2:
            exp = st.date_input("Expiry date *", value=date.today() + timedelta(days=730), key=f"{key}_exp")
            ui.hint("Must be after the manufacturing date.")
            ui.field_error(errors, "expiry_date")
        qty = st.number_input("Number of packs *", min_value=0, max_value=100000, value=20, step=1,
                              key=f"{key}_qty")
        ui.hint(f"1 to {validation.MAX_PACKS_PER_BATCH}. Each pack later gets its own random serial number.")
        ui.field_error(errors, "quantity")

        st.markdown("**3. Raw materials used**")
        lots = st.multiselect("Raw-material lots *", lot_list, format_func=lot_label, key=f"{key}_lots")
        ui.hint("Only lots delivered to this factory are listed.")
        ui.field_error(errors, "lots")
        extra = st.text_input("Other lot IDs (optional)", key=f"{key}_extra", placeholder="e.g. 12, 40")
        ui.hint("For testing: a lot delivered to another factory is refused by the database.")
        ui.field_error(errors, "extra_lots")
        submitted = st.form_submit_button("Register batch", type="primary")

    if submitted:
        bn = batch_no.strip().upper()
        chosen = [l["lot_id"] for l in lots]
        errors = validation.check_batch(bn, mfg, exp, qty, chosen, extra) if ui.checks_on() else {}
        lot_ids = sorted(set(chosen + (validation.parse_id_list(extra) or [])))
        ui.handle_submit(key, errors, lambda: services.create_batch(
            ui.login(), drug["drug_id"], pid, bn, mfg, exp, int(qty), lot_ids))
    ui.stored_result(key)


def generate_packs_form(pid, my_batches):
    key = "generate_packs"
    errors = ui.form_errors(key)
    ui.error_summary(errors, {"batch_id": "Batch"})
    st.write("Packs can be made only for an **APPROVED** batch. New batches are PENDING until "
             "quality control approves them (page *Quality control*).")
    options = [None] + [b for b in my_batches]
    with st.form(key):
        batch = st.selectbox("Batch *", options, key=f"{key}_batch",
                             format_func=lambda b: "Choose a batch" if b is None else
                             f"{b['batch_id']} · {b['batch_no']} · {b['qc_status']} · {b['quantity']} packs")
        other = st.number_input("Or type a batch ID (optional)", min_value=0, value=0, step=1, key=f"{key}_other")
        ui.hint("For testing: another factory's batch is refused for a manufacturer login.")
        ui.field_error(errors, "batch_id")
        submitted = st.form_submit_button("Make packs", type="primary")
    if submitted:
        batch_id = int(other) if other else (batch["batch_id"] if batch else 0)
        errors = validation.check_batch_id(batch_id) if ui.checks_on() else {}
        ui.handle_submit(key, errors, lambda: services.generate_packs(ui.login(), batch_id))
    ui.stored_result(key)


# ---------------------------------------------------------------------
# Shipments (any sender / receiver)
# ---------------------------------------------------------------------
def shipments_page():
    st.header("Shipments")
    st.write("Packs move one handover at a time: the sender dispatches, the receiver scans what arrived.")
    ui.who_can_use("Dispatch: manufacturer M1 (p_5), admin, app. Receive: retailer R1 (p_23), admin, app. "
                   "MySQL refuses the procedure for any other login.")
    pid = ui.choose_actor(["MANUFACTURER", "DISTRIBUTOR", "RETAILER"], "Act for participant *", "ship_actor")
    if not pid:
        return
    tab_send, tab_receive = st.tabs(["Dispatch packs", "Receive a shipment"])
    with tab_send:
        dispatch_form(pid)
    with tab_receive:
        receive_form(pid)


def dispatch_form(pid):
    key = "dispatch"
    errors = ui.form_errors(key)
    ui.error_summary(errors, {"to_id": "Send to", "serials": "Packs"})
    partners = services.partners_of(pid)
    stock = services.my_stock(ui.login(), pid, "IN_STOCK", limit=300)
    if not stock.ok:
        ui.show_error(stock.error)
    serial_options = [p["serial_no"] for p in stock.data] if stock.ok else []
    st.caption("Fields marked * are required.")
    with st.form(key):
        st.markdown("**1. Receiver**")
        to = st.selectbox("Send to *", [None] + partners, key=f"{key}_to",
                          format_func=lambda p: "Choose a trading partner" if p is None else ui.participant_label(p))
        ui.hint("Only participants this sender has a trading link with are listed.")
        other_to = st.number_input("Or type a participant ID (optional)", min_value=0, value=0, step=1,
                                   key=f"{key}_other_to")
        ui.hint("For testing: someone you have no link with is refused (NO_LINK).")
        ui.field_error(errors, "to_id")

        st.markdown("**2. Packs**")
        chosen = st.multiselect("Packs in stock *", serial_options, key=f"{key}_serials")
        ui.hint(f"{len(serial_options)} pack(s) IN_STOCK shown (up to 300).")
        extra = st.text_area("Other serial numbers (optional)", key=f"{key}_extra", height=80,
                             placeholder="One per line, or separated by commas")
        ui.hint("For testing: a pack you do not hold is refused (NOT_OWNER), and the whole shipment is cancelled.")
        ui.field_error(errors, "serials")
        submitted = st.form_submit_button("Dispatch shipment", type="primary")
    if submitted:
        to_id = int(other_to) if other_to else (to["participant_id"] if to else 0)
        serials = list(chosen) + validation.parse_serial_list(extra)
        errors = validation.check_dispatch(to_id, serials) if ui.checks_on() else {}
        ui.handle_submit(key, errors, lambda: services.dispatch(ui.login(), pid, to_id, serials))
    ui.stored_result(key)


def receive_form(pid):
    key = "receive"
    errors = ui.form_errors(key)
    ui.error_summary(errors, {"shipment_id": "Shipment", "extra": "Extra serials"})
    incoming = services.incoming_shipments(pid)
    shipment = st.selectbox("Shipment that arrived *", [None] + incoming, key=f"{key}_ship",
                            format_func=lambda s: "Choose a shipment" if s is None else
                            f"Shipment {s['shipment_id']} from {s['from_name']} · {s['packs']} pack(s) · "
                            f"sent {s['ship_time']}")
    if not incoming:
        st.info("No shipment is on its way to this participant. Dispatch one to it first.")
    listed = services.shipment_serials(shipment["shipment_id"]) if shipment else []
    with st.form(key):
        other = st.number_input("Or type a shipment ID (optional)", min_value=0, value=0, step=1,
                                key=f"{key}_other")
        ui.hint("For testing: a shipment that was already received is refused (NOT_IN_TRANSIT).")
        ui.field_error(errors, "shipment_id")
        st.markdown("**What was in the box**")
        st.caption(f"The dispatch list has {len(listed)} pack(s). All of them count as scanned unless "
                   f"you mark them missing.")
        missing = st.multiselect("Packs NOT in the box (optional)", listed, key=f"{key}_missing")
        extra = st.text_area("Extra serials found in the box (optional)", key=f"{key}_extra", height=80,
                             placeholder="e.g. FAKE00000001")
        ui.hint("Simulates a swap: missing packs and unknown serials are recorded and flagged.")
        ui.field_error(errors, "extra")
        submitted = st.form_submit_button("Record receipt", type="primary")
    if submitted:
        shipment_id = int(other) if other else (shipment["shipment_id"] if shipment else 0)
        base = listed if not other else services.shipment_serials(shipment_id)
        scanned = [s for s in base if s not in set(missing)] + validation.parse_serial_list(extra)
        errors = validation.check_receive(shipment_id, validation.parse_serial_list(extra)) if ui.checks_on() else {}
        ui.handle_submit(key, errors, lambda: services.receive(ui.login(), shipment_id, scanned))
    ui.stored_result(key)


# ---------------------------------------------------------------------
# Sales (retailer)
# ---------------------------------------------------------------------
def sales_page():
    st.header("Sales")
    st.write("A pharmacy sells one pack to a customer. Selling the same serial twice is the sign of a cloned code.")
    ui.who_can_use("Retailer R1 (p_23), and admin / app acting for any retailer.")
    pid = ui.choose_actor(["RETAILER"], "Retailer *", "sale_actor")
    if not pid:
        return
    tab_stock, tab_sell = st.tabs(["My stock", "Sell a pack"])
    stock = services.my_stock(ui.login(), pid)
    with tab_stock:
        if stock.ok:
            counts = {}
            for p in stock.data:
                counts[p["status"]] = counts.get(p["status"], 0) + 1
            cols = st.columns(max(1, len(counts)))
            for col, (status, n) in zip(cols, sorted(counts.items())):
                col.metric(status, n)
            st.caption(f"Read from {stock.message} (first 500 packs).")
            ui.table(stock.data, height=380)
        else:
            ui.show_error(stock.error)
    with tab_sell:
        key = "sell"
        errors = ui.form_errors(key)
        ui.error_summary(errors, {"serial": "Serial number"})
        in_stock = [p["serial_no"] for p in stock.data if p["status"] == "IN_STOCK"] if stock.ok else []
        with st.form(key):
            chosen = st.selectbox("Pack on the shelf", [""] + in_stock, key=f"{key}_choice",
                                  format_func=lambda s: "Choose a pack" if not s else s)
            typed = st.text_input("Or type the serial number on the pack", key=f"{key}_typed",
                                  placeholder="e.g. FK38QD9S4VXK")
            ui.hint("For testing: a serial that was already sold, recalled, or held by another shop is refused.")
            ui.field_error(errors, "serial")
            submitted = st.form_submit_button("Sell pack", type="primary")
        if submitted:
            serial = (typed.strip().upper() if typed.strip() else chosen) or ""
            errors = validation.check_sell(serial) if ui.checks_on() else {}
            ui.handle_submit(key, errors, lambda: services.sell(ui.login(), pid, serial))
        ui.stored_result(key)


# ---------------------------------------------------------------------
# Quality control, recalls and licences (admin / app)
# ---------------------------------------------------------------------
def quality_page():
    st.header("Quality control, recalls and licences")
    ui.who_can_use("Admin and app. A manufacturer cannot approve its own batch: MySQL refuses it.")
    tab_ok, tab_recall, tab_lic = st.tabs(["Approve batches", "Recall a batch", "Licences"])

    with tab_ok:
        pending = services.batches_with_status("PENDING")
        st.caption(f"{len(pending)} batch(es) waiting for quality control.")
        ui.table(pending)
        key = "approve"
        errors = ui.form_errors(key)
        ui.error_summary(errors, {"batch_id": "Batch"})
        with st.form(key):
            batch = st.selectbox("Batch to approve *", [None] + pending, key=f"{key}_batch",
                                 format_func=lambda b: "Choose a batch" if b is None else
                                 f"{b['batch_id']} · {b['batch_no']} · {b['manufacturer']}")
            other = st.number_input("Or type a batch ID (optional)", min_value=0, value=0, step=1, key=f"{key}_other")
            ui.hint("For testing: an already approved batch is refused (BATCH_NOT_PENDING).")
            ui.field_error(errors, "batch_id")
            submitted = st.form_submit_button("Approve batch", type="primary")
        if submitted:
            batch_id = int(other) if other else (batch["batch_id"] if batch else 0)
            errors = validation.check_batch_id(batch_id) if ui.checks_on() else {}
            ui.handle_submit(key, errors, lambda: services.approve_batch(ui.login(), batch_id))
        ui.stored_result(key)

    with tab_recall:
        key = "recall"
        errors = ui.form_errors(key)
        ui.error_summary(errors, {"batch_id": "Batch", "confirm": "Confirmation"})
        st.write("A recall follows the batch's packs through every handover (a recursive query) and "
                 "stops every pack that is not sold yet.")
        with st.form(key):
            batch_id = st.number_input("Batch ID *", min_value=0, value=0, step=1, key=f"{key}_batch")
            confirm = st.checkbox("I understand that every unsold pack of this batch will be recalled *",
                                  key=f"{key}_confirm")
            ui.field_error(errors, "batch_id")
            ui.field_error(errors, "confirm")
            submitted = st.form_submit_button("Recall batch", type="primary")
        if submitted:
            errors = validation.check_batch_id(int(batch_id)) if ui.checks_on() else {}
            if ui.checks_on() and not confirm:
                errors["confirm"] = "Tick the box to confirm the recall."
            ui.handle_submit(key, errors, lambda: services.recall(ui.login(), int(batch_id)))
        ui.stored_result(key)

    with tab_lic:
        key = "licence"
        errors = ui.form_errors(key)
        st.write("Suspend a participant, then try to dispatch from it on *Shipments*: the database refuses "
                 "(LICENSE_NOT_ACTIVE). Every change is logged automatically by a trigger.")
        people = services.participants(["SUPPLIER", "MANUFACTURER", "DISTRIBUTOR", "RETAILER"])
        with st.form(key):
            who = st.selectbox("Participant *", people, format_func=lambda p: ui.participant_label(p) +
                               f" · licence {p['license_status']}", key=f"{key}_who")
            status = st.selectbox("New licence status *", ["SUSPENDED", "ACTIVE", "REVOKED"], key=f"{key}_status")
            ui.hint("Remember to set it back to ACTIVE after the demo.")
            submitted = st.form_submit_button("Change licence", type="primary")
        if submitted:
            ui.handle_submit(key, {}, lambda: services.set_license(ui.login(), who["participant_id"], status))
        ui.stored_result(key)
