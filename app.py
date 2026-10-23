"""Tolerance Stack-up Studio - Streamlit front end.

All calculations live in the ``stackup`` package; this file only handles
editing, layout and downloads.  Run with:  streamlit run app.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from stackup import controlplan, pfmea, stack
from stackup.excel import workbook_bytes
from stackup.plots import contribution_figure, gap_figure, rpn_pareto

DATA_DIR = Path(__file__).parent / "data"
PAGES = ["📏 Stack-up", "⚠️ PFMEA", "📋 Control plan", "🔗 Traceability & export"]

st.set_page_config(page_title="Tolerance Stack-up Studio", page_icon="📏", layout="wide")


@st.cache_data
def load_sample(name: str) -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / name, encoding="utf-8")


def state_frame(key: str, sample: str) -> pd.DataFrame:
    if key not in st.session_state:
        st.session_state[key] = load_sample(sample)
    return st.session_state[key]


def editor(key: str, sample: str, **kwargs) -> pd.DataFrame:
    # data_editor stores edits as deltas against its input, so the input must stay fixed while the
    # widget lives.  Refresh it from the saved frame only when the widget is new (e.g. after a page switch).
    widget, src = f"{key}_editor", f"{key}_src"
    if widget not in st.session_state or src not in st.session_state:
        st.session_state[src] = state_frame(key, sample)
    df = st.data_editor(st.session_state[src], num_rows="dynamic", width="stretch", key=widget, **kwargs)
    st.session_state[key] = df
    return df


def current():
    """Parse whatever is in the editors; return (dims, modes, plan, errors)."""
    errors, dims, modes, plan = [], [], [], []
    try:
        dims = stack.from_frame(state_frame("stack", "end_play_stack.csv").dropna(subset=["name"]))
    except (ValueError, TypeError) as e:
        errors.append(f"Stack-up: {e}")
    try:
        modes = pfmea.from_frame(state_frame("pfmea", "pfmea.csv").dropna(subset=["id"]))
    except (ValueError, TypeError) as e:
        errors.append(f"PFMEA: {e}")
    try:
        plan = controlplan.from_frame(state_frame("plan", "control_plan.csv").dropna(subset=["characteristic"]))
    except (ValueError, TypeError) as e:
        errors.append(f"Control plan: {e}")
    return dims, modes, plan, errors


# ------------------------------------------------------------------ sidebar
st.sidebar.title("📏 Tolerance Stack-up Studio")
page = st.sidebar.radio("Page", PAGES, key="page")
st.sidebar.number_input("Gap LSL (mm)", value=0.10, step=0.01, format="%.3f", key="lsl")
st.sidebar.number_input("Gap USL (mm)", value=0.60, step=0.01, format="%.3f", key="usl")
st.sidebar.number_input("RPN action threshold", value=100, step=10, key="rpn_threshold")
st.sidebar.caption("Sample: axial end play of a gearbox shaft (housing, two 6204 bearings, spacer). "
                   "Edit any table; every page updates.")
lsl, usl, thr = st.session_state.lsl, st.session_state.usl, int(st.session_state.rpn_threshold)

# ----------------------------------------------------------------- stack-up
if page == PAGES[0]:
    st.header("1-D tolerance stack-up")
    st.caption("gap = Σ direction × dimension. Direction +1 opens the gap, -1 closes it. "
               "Lower deviation is signed (e.g. -0.12). Cp is the process capability the statistical methods assume.")
    editor("stack", "end_play_stack.csv", column_config={
        "direction": st.column_config.SelectboxColumn(options=[1, -1]),
        "distribution": st.column_config.SelectboxColumn(options=list(stack.DISTRIBUTIONS))})
    dims, _, _, errors = current()
    if errors and dims == []:
        st.error(errors[0])
        st.stop()
    r = stack.analyze(dims, lsl, usl)
    mc = stack.monte_carlo(dims, lsl, usl, n=200_000)
    c = st.columns(5)
    c[0].metric("Mean gap", f"{r.mean_gap:.4f}", f"nominal {r.nominal_gap:.4f}", delta_color="off")
    c[1].metric("Worst case", f"{r.wc_limits[0]:.3f} - {r.wc_limits[1]:.3f}",
                "PASS" if r.passes(r.wc_limits) else "FAIL", delta_color="normal" if r.passes(r.wc_limits) else "inverse")
    c[2].metric("RSS", f"{r.rss_limits[0]:.3f} - {r.rss_limits[1]:.3f}",
                "PASS" if r.passes(r.rss_limits) else "FAIL", delta_color="normal" if r.passes(r.rss_limits) else "inverse")
    c[3].metric("Predicted gap Cpk", f"{r.cpk:.2f}", f"{r.ppm:.3g} ppm (normal model)", delta_color="off")
    c[4].metric("Monte Carlo", f"{mc.ppm:.1f} ppm", f"σ {mc.std:.4f} vs model {r.sigma_gap:.4f}", delta_color="off")
    st.plotly_chart(gap_figure(r, mc), width="stretch")
    left, right = st.columns([3, 2])
    left.plotly_chart(contribution_figure(r), width="stretch")
    right.subheader("Contributions")
    right.dataframe(r.contributions.round(4), hide_index=True, width="stretch")
    if not r.passes(r.wc_limits) and r.passes(r.rss_limits):
        st.info("Worst case fails but RSS passes. Accepting the statistical result is a decision: it only holds "
                "if every dimension really is centred and at least as capable as assumed. The **Traceability** "
                "page checks that the control plan enforces those Cp assumptions.")

# -------------------------------------------------------------------- PFMEA
elif page == PAGES[1]:
    st.header("Process FMEA")
    st.caption("AIAG 4th edition 1-10 scales. RPN = S × O × D. Severity 9-10 is High priority whatever the RPN.")
    editor("pfmea", "pfmea.csv")
    _, modes, _, errors = current()
    for e in errors:
        if e.startswith("PFMEA"):
            st.error(e)
    if modes:
        df = pfmea.ranked(modes, thr)
        c = st.columns(3)
        for col, level in zip(c, ("High", "Medium", "Low")):
            col.metric(f"{level} priority", int((df["priority"] == level).sum()))
        st.plotly_chart(rpn_pareto(df), width="stretch")
        st.subheader("Ranked by risk")
        st.dataframe(df[["id", "step", "failure_mode", "severity", "occurrence", "detection", "rpn", "priority",
                         "special_char", "action"]], hide_index=True, width="stretch")

# ------------------------------------------------------------- control plan
elif page == PAGES[2]:
    st.header("Control plan")
    st.caption("Link each line to the PFMEA ids it controls and, for stack-up dimensions, the dimension name.")
    editor("plan", "control_plan.csv")

# ----------------------------------------------------- traceability/export
else:
    st.header("Traceability & export")
    dims, modes, plan, errors = current()
    for e in errors:
        st.error(e)
    if not errors:
        findings = (controlplan.check_pfmea_coverage(modes, plan, thr)
                    + controlplan.check_stack_assumptions(dims, plan))
        if findings:
            for f in findings:
                (st.error if f.level == "error" else st.warning)(f.message)
        else:
            st.success("All checks pass: every special characteristic and Medium/High PFMEA line is controlled, "
                       "and every Cp the stack-up assumes is required by the control plan.")
        mc = stack.monte_carlo(dims, lsl, usl, n=200_000)
        st.download_button("⬇️ Download Excel workbook (live formulas)", key="xlsx",
                           data=workbook_bytes(dims, lsl, usl, mc, 200_000, modes, plan, findings, thr),
                           file_name="stackup_pfmea_control_plan.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.caption("Stack-up, PFMEA (RPN and priority as formulas), control plan, Monte Carlo summary and these checks.")
