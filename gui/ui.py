"""
Small screen helpers shared by every page.

  form_errors / error_summary / field_error
      the validation pattern from the teacher's example: a red summary box
      listing every problem, and each message under its own field. The
      values typed stay in the fields (Streamlit keeps them by key).
  show_result
      success message, or the explained refusal from gui/errors.py with
      the exact MySQL message under it.
"""

import pandas as pd
import streamlit as st

KIND_HEADING = {
    "denied": "SECURITY",
    "rule": "BUSINESS RULE",
    "constraint": "DATA RULE",
    "login": "LOGIN",
    "connection": "CONNECTION",
    "other": "DATABASE",
}


def rerun():
    fn = getattr(st, "rerun", None) or getattr(st, "experimental_rerun")
    fn()


def login():
    return st.session_state.get("login")


def checks_on():
    return st.session_state.get("form_checks", True)


# ---------------------------------------------------------------------
# Validation display
# ---------------------------------------------------------------------
def form_errors(key):
    return st.session_state.get(f"{key}__errors", {})


def error_summary(errors, labels):
    if not errors:
        return
    n = len(errors)
    lines = "\n".join(f"- **{labels.get(f, f)}:** {m}" for f, m in errors.items())
    st.error(f"**Please fix {n} problem{'s' if n > 1 else ''}**\n\n{lines}")


def field_error(errors, field):
    if field in errors:
        st.markdown(f":red[{errors[field]}]")


def hint(text):
    st.caption(text)


def handle_submit(key, errors, action):
    """
    After a form is submitted:
      problems found -> remember them and redraw, so they show under the fields
      no problems    -> run the action (a services.* call), remember its result
    """
    if errors:
        st.session_state[f"{key}__errors"] = errors
        st.session_state.pop(f"{key}__result", None)
    else:
        st.session_state[f"{key}__errors"] = {}
        with st.spinner("Working..."):
            try:
                st.session_state[f"{key}__result"] = action()
            except Exception as e:      # MongoDB down, missing module, ...
                st.session_state[f"{key}__result"] = crash_result(e)
    rerun()


def stored_result(key):
    res = st.session_state.get(f"{key}__result")
    if res is not None:
        show_result(res)


def crash_result(e):
    from gui.services import Result
    return Result(False, error={"kind": "connection", "title": "Something outside MySQL failed",
                                "detail": "Check that MongoDB is running and the .env settings are right.",
                                "enforced_by": "-", "raw": f"{type(e).__name__}: {e}"})


# ---------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------
def show_error(info):
    heading = KIND_HEADING.get(info["kind"], "DATABASE")
    text = f"**{heading} — {info['title']}**\n\n{info['detail']}"
    if info.get("enforced_by") and info["enforced_by"] != "-":
        text += f"\n\n*Enforced by:* {info['enforced_by']}"
    if info["kind"] == "denied":
        st.error("⛔ " + text)
    else:
        st.error(text)
    if info.get("raw"):
        st.caption("Exact message from the server:")
        st.code(info["raw"], language="text")


def show_result(res):
    if res.ok:
        if res.message:
            st.success(res.message)
    else:
        show_error(res.error)
    for title, rows in res.tables:
        if rows:
            st.markdown(f"**{title}**")
            table(rows)
    if res.log:
        with st.expander("Output of the script"):
            st.code(res.log, language="text")


def table(rows, height=None):
    if not rows:
        st.info("No rows.")
        return
    df = pd.DataFrame(rows)
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].map(lambda v: v if v is None or isinstance(v, (int, float, str)) else str(v))
    # no width option: its name changed between Streamlit versions
    if height:
        st.dataframe(df, height=height)
    else:
        st.dataframe(df)


def who_can_use(text):
    st.caption(f"🔐 {text}")


def participant_label(p):
    return f"{p['participant_id']} · {p['name']} ({p['participant_type'].title()}, {p.get('city') or '-'})"


def choose_actor(types, label, key):
    """
    The participant this page acts for.
      p_<id> logins: fixed to their own participant (shown, not chosen).
      admin / app:   choose any participant of the right type.
    Returns the participant id.
    """
    from gui import services
    acc = login()["account"]
    if acc["participant"]:
        pid = acc["participant"]
        st.info(f"You are acting as participant **{pid}** ({acc['who']}). "
                f"This login can only act for itself.")
        return pid
    people = services.participants(types)
    if not people:
        st.warning("No participants of this type.")
        return None
    chosen = st.selectbox(label, people, format_func=participant_label, key=key)
    return chosen["participant_id"]
