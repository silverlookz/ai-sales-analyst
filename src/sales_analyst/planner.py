"""Natural language -> SQL.

Two planners behind one interface:
  * LLMPlanner      - LangChain + OpenAI, prompted with the schema and the
                      governed metric definitions (needs OPENAI_API_KEY).
  * SemanticPlanner - deterministic parser over a small semantic layer
                      (metrics, dimensions, filters). Runs offline and makes
                      the business definitions explicit and testable.

Both return SQL that is then validated by guardrails.validate_sql.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

BASE_FROM = """FROM fact_order_lines f
JOIN dim_product p  ON p.product_id = f.product_id
JOIN dim_customer c ON c.customer_id = f.customer_id
JOIN dim_region r   ON r.region_id = c.region_id
JOIN dim_date d     ON d.date_key = f.order_date"""

# Governed metric definitions: the single source of truth for "revenue", "margin", ...
METRICS = {
    "revenue": ("ROUND(SUM(f.revenue), 2)", ["revenue", "sales", "turnover"]),
    "gross_profit": ("ROUND(SUM(f.revenue - f.cost), 2)", ["profit", "gross profit"]),
    "margin_pct": ("ROUND(100.0 * SUM(f.revenue - f.cost) / SUM(f.revenue), 1)", ["margin"]),
    "orders": ("COUNT(DISTINCT f.order_id)", ["orders", "order count", "number of orders"]),
    "units": ("SUM(f.quantity)", ["units", "quantity", "volume"]),
    "avg_order_value": ("ROUND(SUM(f.revenue) / COUNT(DISTINCT f.order_id), 2)",
                        ["average order value", "aov", "avg order"]),
    "customers": ("COUNT(DISTINCT f.customer_id)", ["customers", "buyers", "accounts"]),
}

DIMENSIONS = {  # name: (sql expression, trigger phrases, is_time)
    "month": ("substr(f.order_date, 1, 7)", ["month", "monthly", "trend", "over time"], True),
    "quarter": ("d.year || '-Q' || d.quarter", ["quarter", "quarterly"], True),
    "year": ("d.year", ["year", "yearly", "annual", "yoy", "year over year"], True),
    "region": ("r.region_name", ["region", "province"], False),
    "zone": ("r.zone", ["zone"], False),
    "category": ("p.category", ["category", "categories"], False),
    "product": ("p.product_name", ["product", "products", "sku"], False),
    "segment": ("c.segment", ["segment", "segments"], False),
    "channel": ("f.channel", ["channel", "channels"], False),
    "customer": ("c.customer_name", ["customer", "client"], False),
}

FILTER_VALUES = {
    "r.region_name": ["Ontario", "Quebec", "British Columbia", "Alberta", "Atlantic", "Prairies"],
    "p.category": ["Computers", "Displays", "Accessories", "Audio", "Services"],
    "c.segment": ["Enterprise", "Mid-Market", "Small Business", "Consumer"],
    "f.channel": ["Online", "Direct Sales", "Partner"],
}


@dataclass
class QueryPlan:
    sql: str
    metric: str
    dimension: str | None = None
    filters: list[str] = field(default_factory=list)
    is_time_series: bool = False
    planner: str = "semantic"


class PlanningError(ValueError):
    pass


def _has(text: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


class SemanticPlanner:
    name = "semantic"

    def plan(self, question: str) -> QueryPlan:
        q = question.lower()

        metric = next((m for m, (_, words) in sorted(METRICS.items(), key=lambda kv: -max(len(w) for w in kv[1][1]))
                       if any(_has(q, w) for w in words)), None)
        if metric is None:
            if re.search(r"\b(best|top|worst)\b", q):
                metric = "revenue"
            else:
                raise PlanningError(
                    "I couldn't tell which measure you want. Try revenue, profit, margin, orders, units, "
                    "average order value or customers.")

        # "by X" wins; otherwise the first dimension mentioned
        dimension = None
        by = re.search(r"\b(?:by|per|for each|across)\s+(\w+(?:\s\w+)?)", q)
        candidates = [by.group(1)] if by else []
        candidates.append(q)
        for text in candidates:
            for name, (_, words, _) in DIMENSIONS.items():
                if any(_has(text, w) for w in words):
                    dimension = name
                    break
            if dimension:
                break

        filters, where = [], []
        years = re.findall(r"\b(202[0-9])\b", q)
        quarter = re.search(r"\bq([1-4])\b", q)
        if years and not (dimension == "year" and len(years) > 1):
            where.append(f"d.year IN ({', '.join(sorted(set(years)))})" if len(set(years)) > 1
                         else f"d.year = {years[0]}")
            filters.append(f"year={','.join(sorted(set(years)))}")
        if quarter:
            where.append(f"d.quarter = {quarter.group(1)}")
            filters.append(f"quarter=Q{quarter.group(1)}")
        for column, values in FILTER_VALUES.items():
            dim_expr = DIMENSIONS[dimension][0] if dimension else None
            for v in values:
                if _has(q, v.lower()) and column != dim_expr:
                    where.append(f"{column} = '{v}'")
                    filters.append(f"{column.split('.')[1]}={v}")

        metric_sql = METRICS[metric][0]
        where_sql = f"\nWHERE {' AND '.join(where)}" if where else ""
        top = re.search(r"\b(?:top|best|worst|bottom)\s+(\d+)\b", q)
        ascending = re.search(r"\b(worst|bottom|lowest|least)\b", q) is not None

        if dimension:
            dim_sql, _, is_time = DIMENSIONS[dimension]
            order = f"{dimension} ASC" if is_time else f"{metric} {'ASC' if ascending else 'DESC'}"
            limit = f"\nLIMIT {top.group(1)}" if top else ""
            sql = (f"SELECT {dim_sql} AS {dimension}, {metric_sql} AS {metric}\n{BASE_FROM}{where_sql}\n"
                   f"GROUP BY 1\nORDER BY {order}{limit}")
            return QueryPlan(sql, metric, dimension, filters, is_time)

        sql = f"SELECT {metric_sql} AS {metric}\n{BASE_FROM}{where_sql}"
        return QueryPlan(sql, metric, None, filters, False)


SCHEMA_DOC = """SQLite star schema:
fact_order_lines(line_id, order_id, order_date TEXT 'YYYY-MM-DD', customer_id, product_id,
                 channel TEXT, quantity INT, discount_pct REAL, revenue REAL, cost REAL)
dim_product(product_id, product_name, category, unit_price, unit_cost)
dim_customer(customer_id, customer_name, segment, region_id)
dim_region(region_id, region_name, zone)
dim_date(date_key TEXT, year INT, quarter INT, month INT, month_name TEXT)

Governed metric definitions (use exactly these):
""" + "\n".join(f"- {m}: {expr}" for m, (expr, _) in METRICS.items())


class LLMPlanner:  # pragma: no cover - needs network + key
    name = "llm"

    def __init__(self):
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_openai import ChatOpenAI

        self.chain = ChatPromptTemplate.from_messages([
            ("system", "You write a single read-only SQLite SELECT query answering the user's "
                       "question. Use aliases f, p, c, r, d. Return ONLY the SQL, no prose, no "
                       "markdown.\n\n" + SCHEMA_DOC),
            ("human", "{question}"),
        ]) | ChatOpenAI(model=os.getenv("CHAT_MODEL", "gpt-4o-mini"), temperature=0)

    def plan(self, question: str) -> QueryPlan:
        sql = self.chain.invoke({"question": question}).content.strip()
        sql = re.sub(r"^```(?:sql)?|```$", "", sql, flags=re.MULTILINE).strip()
        is_time = bool(re.search(r"order_date|d\.year|quarter|month", sql.split("FROM")[0], re.I))
        return QueryPlan(sql, metric="value", planner="llm", is_time_series=is_time)


def get_planner():
    return LLMPlanner() if os.getenv("OPENAI_API_KEY") else SemanticPlanner()
