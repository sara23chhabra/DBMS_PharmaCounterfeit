"""
Pharma Counterfeit DBMS: the GUI.

Run from the project folder:
    streamlit run app.py

Login uses the real MySQL accounts (sessions/09_create_demo_users.sql):
MySQL checks the password, and every action runs as that account.
"""

import streamlit as st

st.set_page_config(page_title="PharmaTrace", page_icon="💊", layout="wide")

from gui import settings, services, ui  # noqa: E402  (after set_page_config)
from gui import pages_checks, pages_ops  # noqa: E402

# Which pages appear in the menu for which role. This is only for a tidy menu:
# the protection is in MySQL. Tick "Show every page" to try them all.
PAGES = {
    "Home": None,
    "Verify a pack": None,
    "Batches": {"role_admin", "role_app", "role_manufacturer"},
    "Shipments": {"role_admin", "role_app", "role_manufacturer", "role_retailer"},
    "Sales": {"role_admin", "role_app", "role_retailer"},
    "Quality control": {"role_admin", "role_app"},
    "Detection": {"role_admin", "role_detection", "role_readonly"},
    "Ledger integrity": {"role_admin", "role_ledger", "role_readonly"},
    "Security lab": None,
    "Demo helper": {"role_admin"},
}

ROLE_CAN = {
    "role_admin": "everything in the project database; still cannot edit history (trigger) or read MySQL's own tables",
    "role_app": "read and add records, run every procedure; cannot change or delete history or shipments",
    "role_manufacturer": "only its own batches and stock (views); register batches, make packs, dispatch",
    "role_retailer": "only its own stock (view); receive shipments, sell packs",
    "role_detection": "read the real tables and add flags; never the answer key",
    "role_ledger": "read, and change only the ledger_synced column",
    "role_readonly": "read the views only",
}


def login_page():
    st.header("Log in")
    st.write("Each login is a real MySQL account with its own role. MySQL checks the password.")
    key = "login_form"
    errors = ui.form_errors(key)
    ui.error_summary(errors, {"password": "Password"})
    with st.form(key):
        acc = st.selectbox("Account *", settings.ACCOUNTS, key=f"{key}_acc",
                           format_func=lambda a: f"{a['user']} — {a['who']}")
        pw = st.text_input("Password *", type="password", key=f"{key}_pw")
        ui.hint("The password set when the demo users were created (see your .env file).")
        ui.field_error(errors, "password")
        submitted = st.form_submit_button("Log in", type="primary")
    if submitted:
        if ui.checks_on() and not pw:
            st.session_state[f"{key}__errors"] = {"password": "Enter the password."}
            ui.rerun()
        res = services.check_login(acc["user"], pw)
        st.session_state[f"{key}__errors"] = {}
        if res.ok:
            st.session_state["login"] = {"user": acc["user"], "password": pw, "account": acc,
                                         "mysql": res.data}
            st.session_state["page"] = "Home"
            ui.rerun()
        else:
            ui.show_error(res.error)
    st.divider()
    st.write("Customers have no account: they can use **Verify a pack** without logging in.")


def home_page():
    st.header("PharmaTrace: counterfeit-proof medicine supply chain")
    lg = ui.login()
    st.success(f"MySQL confirms you are **{lg['mysql']['current_user']}** with role "
               f"`{lg['mysql']['roles']}`.")
    st.write(f"**This account may:** {ROLE_CAN.get(lg['account']['role'], '-')}.")
    try:
        c = services.overview_counts()
        cols = st.columns(6)
        for col, (label, k) in zip(cols, [("Participants", "participants"), ("Batches", "batches"),
                                          ("Packs", "packs"), ("Shipments", "shipments"),
                                          ("History events", "events"), ("Open flags", "open_flags")]):
            col.metric(label, f"{c[k]:,}")
    except Exception as e:
        ui.show_result(ui.crash_result(e))
    st.markdown("""
**The chain:** Supplier → Manufacturer → Distributor → Retailer → Consumer

**Three layers protect it**
1. **MySQL** keeps every record and enforces the rules: constraints, triggers, stored procedures, and a
   separate account with its own permissions for each kind of user.
2. **The ledger** (MongoDB) holds a hash chain of every record, so any later change to history is caught.
3. **Detection rules** look for counterfeit patterns (missing packs, unknown serials, codes sold twice, ...).

Use the menu on the left. The sidebar switch *Form checks* decides whether the forms check your input
first, or send it straight to the database so you can see MySQL refuse it on its own.
""")
    with st.expander("All accounts and what MySQL lets them do"):
        ui.table([{"account": a["user"], "who": a["who"], "role": a["role"],
                   "may": ROLE_CAN[a["role"]]} for a in settings.ACCOUNTS])


def sidebar():
    with st.sidebar:
        st.title("💊 PharmaTrace")
        lg = ui.login()
        if lg:
            st.markdown(f"Logged in as **{lg['user']}**  \n{lg['account']['who']}")
            if st.button("Log out"):
                for k in list(st.session_state):
                    del st.session_state[k]
                ui.rerun()
        else:
            st.markdown("Not logged in")
        st.divider()
        if lg:
            show_all = st.checkbox("Show every page", key="show_all",
                                   help="Open pages this account should not use, to see MySQL refuse it.")
            role = lg["account"]["role"]
            names = [n for n, roles in PAGES.items() if show_all or roles is None or role in roles]
        else:
            names = ["Log in", "Verify a pack"]
        current = st.session_state.get("page")
        if current not in names:
            current = names[0]
        page = st.radio("Go to", names, index=names.index(current))
        st.session_state["page"] = page
        st.divider()
        st.checkbox("Form checks on", value=True, key="form_checks",
                    help="Off: input goes straight to MySQL, to show the database's own rules.")
        if not st.session_state.get("form_checks", True):
            st.caption("Form checks are OFF: bad input now reaches MySQL, which refuses it itself.")
        if not settings.ENV_FOUND:
            st.warning("No .env file found in the project folder.")
        st.caption(f"Database: {settings.DB_NAME} on {settings.MYSQL_HOST}")
    return page


def main():
    page = sidebar()
    routes = {
        "Log in": login_page, "Home": home_page, "Verify a pack": pages_checks.verify_page,
        "Batches": pages_ops.batches_page, "Shipments": pages_ops.shipments_page,
        "Sales": pages_ops.sales_page, "Quality control": pages_ops.quality_page,
        "Detection": pages_checks.detection_page, "Ledger integrity": pages_checks.ledger_page,
        "Security lab": pages_checks.security_page, "Demo helper": pages_checks.demo_page,
    }
    try:
        routes[page]()
    except Exception as e:  # MySQL or MongoDB not reachable, etc.
        ui.show_result(ui.crash_result(e))
    st.caption("Pharma Counterfeit DBMS project · demo data only")


main()
