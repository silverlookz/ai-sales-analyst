import sqlite3

import pytest

from sales_analyst.guardrails import UnsafeSQLError, read_only_connection, validate_sql


@pytest.mark.parametrize("sql", [
    "DROP TABLE dim_product",
    "SELECT 1; DELETE FROM fact_order_lines",
    "UPDATE dim_product SET unit_price = 0",
    "SELECT * FROM sqlite_master",
    "SELECT * FROM fact_order_lines f JOIN secrets s ON 1=1",
    "PRAGMA table_info(dim_product)",
    "",
])
def test_rejects_unsafe(sql):
    with pytest.raises(UnsafeSQLError):
        validate_sql(sql)


def test_adds_limit_and_allows_ctes():
    sql = validate_sql("WITH t AS (SELECT * FROM dim_product) SELECT * FROM t")
    assert sql.endswith("LIMIT 1000")


def test_keeps_existing_limit():
    assert validate_sql("SELECT * FROM dim_region LIMIT 5").endswith("LIMIT 5")


def test_engine_blocks_writes_even_if_validation_bypassed(db_path):
    con = read_only_connection(str(db_path))
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("DELETE FROM dim_region")
    assert con.execute("SELECT COUNT(*) FROM dim_region").fetchone()[0] == 6
