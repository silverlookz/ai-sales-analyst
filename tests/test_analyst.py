import pytest
from fastapi.testclient import TestClient

from sales_analyst.analyst import SalesAnalyst
from sales_analyst.planner import PlanningError, SemanticPlanner


@pytest.fixture(scope="module")
def analyst(db_path):
    return SalesAnalyst(db_path, planner=SemanticPlanner())


def test_revenue_by_region(analyst):
    r = analyst.ask("Revenue by region in 2025")
    assert list(r.data.columns) == ["region", "revenue"]
    assert len(r.data) == 6 and r.chart_type == "bar"
    assert r.data["revenue"].is_monotonic_decreasing
    assert "leads" in r.narrative


def test_time_series(analyst):
    r = analyst.ask("Monthly revenue trend for 2025")
    assert len(r.data) == 12 and r.chart_type == "line"


def test_top_n_and_filters(analyst):
    r = analyst.ask("Top 3 products by gross profit in Ontario")
    assert len(r.data) == 3 and "Ontario" in r.sql


def test_scalar(analyst):
    r = analyst.ask("How many orders in 2024?")
    assert r.data.shape == (1, 1) and r.chart_type is None


def test_metric_consistency(analyst):
    total = analyst.ask("Total revenue").data.iloc[0, 0]
    by_region = analyst.ask("Revenue by region").data["revenue"].sum()
    assert abs(total - by_region) < 1


def test_unknown_metric(analyst):
    with pytest.raises(PlanningError):
        analyst.ask("Tell me a joke")


def test_api(db_path, monkeypatch):
    import api.main as m
    m.analyst.cache_clear()
    monkeypatch.setattr(m, "SalesAnalyst", lambda: SalesAnalyst(db_path, SemanticPlanner()))
    client = TestClient(m.app)
    r = client.post("/ask", json={"question": "Revenue by channel"})
    assert r.status_code == 200 and len(r.json()["rows"]) == 3
    assert client.post("/ask", json={"question": "sing a song"}).status_code == 422
