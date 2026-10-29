"""Streamlit UI.  Run: streamlit run app/streamlit_app.py"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sales_analyst.analyst import SalesAnalyst  # noqa: E402
from sales_analyst.guardrails import UnsafeSQLError  # noqa: E402
from sales_analyst.planner import PlanningError  # noqa: E402

st.set_page_config(page_title="AI Sales Analyst", page_icon="📊", layout="wide")
analyst = st.cache_resource(SalesAnalyst)()

st.title("📊 AI Sales Analyst")
st.caption(f"Ask business questions in plain English · planner: {analyst.planner.name}")

examples = ["Revenue by region in 2025", "Monthly revenue trend for 2025",
            "Top 5 products by gross profit", "Margin by category in Q4 2025",
            "Average order value by segment", "Revenue by channel for Enterprise"]
cols = st.columns(3)
for i, ex in enumerate(examples):
    if cols[i % 3].button(ex, use_container_width=True):
        st.session_state["q"] = ex

q = st.text_input("Your question", value=st.session_state.get("q", ""))
if q:
    try:
        r = analyst.ask(q)
    except (PlanningError, UnsafeSQLError) as exc:
        st.warning(str(exc))
    else:
        st.markdown(r.narrative)
        if r.chart_type:
            data = r.data.set_index(r.data.columns[0])
            (st.line_chart if r.chart_type == "line" else st.bar_chart)(data)
        left, right = st.columns([3, 2])
        left.dataframe(r.data, use_container_width=True, hide_index=True)
        right.code(r.sql, language="sql")
