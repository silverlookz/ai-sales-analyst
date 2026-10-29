"""The analyst: question -> plan -> safe SQL -> data -> chart -> narrative."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .guardrails import read_only_connection, validate_sql
from .planner import QueryPlan, get_planner

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "sales.db"


@dataclass
class AnalysisResult:
    question: str
    sql: str
    data: pd.DataFrame
    narrative: str
    chart_type: str | None
    planner: str


def _fmt(metric: str, value: float) -> str:
    if metric in {"revenue", "gross_profit", "avg_order_value"}:
        return f"${value:,.0f}"
    if metric == "margin_pct":
        return f"{value:.1f}%"
    return f"{value:,.0f}"


def narrate(plan: QueryPlan, df: pd.DataFrame) -> str:
    if df.empty:
        return "No data matched that question."
    metric = df.columns[-1]
    label = metric.replace("_", " ")
    scope = f" ({', '.join(plan.filters)})" if plan.filters else ""
    if df.shape[1] == 1:
        return f"Total {label}{scope}: **{_fmt(metric, df.iloc[0, 0])}**."

    dim = df.columns[0]
    labels, values = df[dim].tolist(), df[metric].tolist()
    if plan.is_time_series and len(df) >= 2:
        change = (values[-1] - values[0]) / values[0] * 100 if values[0] else 0
        peak = max(range(len(values)), key=values.__getitem__)
        return (f"{label.capitalize()}{scope} moved from {_fmt(metric, values[0])} in {labels[0]} "
                f"to {_fmt(metric, values[-1])} in {labels[-1]} ({change:+.1f}%). "
                f"Peak was {labels[peak]} at {_fmt(metric, values[peak])}.")

    ascending = len(values) > 1 and values[0] < values[-1]
    verb = "is lowest" if ascending else "leads"
    text = f"**{labels[0]}** {verb} on {label}{scope} with {_fmt(metric, values[0])}"
    if metric not in {"margin_pct", "avg_order_value"} and sum(values) and not ascending:
        text += f", {values[0] / sum(values) * 100:.0f}% of the total shown"
    if len(df) > 1:
        other = "Highest" if ascending else "Lowest"
        text += f". {other} shown is {labels[-1]} at {_fmt(metric, values[-1])}"
    return text + "."


def llm_narrative(question: str, df: pd.DataFrame) -> str:  # pragma: no cover
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(model=os.getenv("CHAT_MODEL", "gpt-4o-mini"), temperature=0.2)
    prompt = (f"Question: {question}\nResult table (CSV):\n{df.head(50).to_csv(index=False)}\n\n"
              "Write 2-3 sentences of business insight using only numbers from the table.")
    return llm.invoke(prompt).content.strip()


class SalesAnalyst:
    def __init__(self, db_path: str | Path = DEFAULT_DB, planner=None):
        self.db_path = str(db_path)
        if not Path(self.db_path).exists():
            raise FileNotFoundError(f"{db_path} not found. Run: python scripts/generate_data.py")
        self.planner = planner or get_planner()

    def ask(self, question: str) -> AnalysisResult:
        plan = self.planner.plan(question)
        sql = validate_sql(plan.sql)
        con = read_only_connection(self.db_path)
        try:
            df = pd.read_sql_query(sql, con)
        finally:
            con.close()
        chart = None
        if df.shape[1] >= 2 and len(df) > 1:
            chart = "line" if plan.is_time_series else "bar"
        narrative = llm_narrative(question, df) if plan.planner == "llm" else narrate(plan, df)
        return AnalysisResult(question, sql, df, narrative, chart, plan.planner)

    @staticmethod
    def save_chart(result: AnalysisResult, path: str | Path) -> Path | None:
        if not result.chart_type:
            return None
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        df = result.data
        x, y = df.columns[0], df.columns[-1]
        fig, ax = plt.subplots(figsize=(9, 4.5))
        if result.chart_type == "line":
            ax.plot(df[x].astype(str), df[y], marker="o", color="#2563eb")
            ax.tick_params(axis="x", rotation=45)
        else:
            ax.barh(df[x].astype(str)[::-1], df[y][::-1], color="#2563eb")
        from matplotlib.ticker import FuncFormatter

        def tick(v, _):
            if y in {"revenue", "gross_profit", "avg_order_value"}:
                return f"${v / 1e6:.1f}M" if abs(v) >= 1e6 else f"${v / 1e3:.0f}K" if abs(v) >= 1e3 else f"${v:.0f}"
            return f"{v:.0f}%" if y == "margin_pct" else f"{v:,.0f}"

        (ax.yaxis if result.chart_type == "line" else ax.xaxis).set_major_formatter(FuncFormatter(tick))
        ax.set_title(result.question, fontsize=11, loc="left")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y" if result.chart_type == "line" else "x", alpha=0.3)
        fig.tight_layout()
        fig.savefig(path, dpi=120)
        plt.close(fig)
        return Path(path)


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) or "Revenue by region in 2025"
    r = SalesAnalyst().ask(q)
    print(f"\n{q}\n\nSQL:\n{r.sql}\n\n{r.data.to_string(index=False)}\n\n{r.narrative}\n")
