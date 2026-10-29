"""FastAPI service.  Run: PYTHONPATH=src uvicorn api.main:app --reload"""
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from sales_analyst.analyst import SalesAnalyst
from sales_analyst.guardrails import UnsafeSQLError
from sales_analyst.planner import PlanningError

app = FastAPI(title="AI Sales Analyst", version="1.0.0")


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=300)


@lru_cache(maxsize=1)
def analyst() -> SalesAnalyst:
    return SalesAnalyst()


@app.get("/health")
def health():
    return {"status": "ok", "planner": analyst().planner.name}


@app.post("/ask")
def ask(req: AskRequest):
    try:
        r = analyst().ask(req.question)
    except (PlanningError, UnsafeSQLError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"question": r.question, "sql": r.sql, "narrative": r.narrative,
            "chart_type": r.chart_type, "planner": r.planner,
            "columns": list(r.data.columns), "rows": r.data.to_dict(orient="records")}
