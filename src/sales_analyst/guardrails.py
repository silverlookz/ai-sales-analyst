"""SQL safety layer.

LLM-generated SQL is untrusted input. Three independent defences:
  1. Static checks: one statement, SELECT/WITH only, allow-listed tables, no
     dangerous keywords.
  2. Row cap: a LIMIT is enforced on every query.
  3. Engine-level: the connection is opened read-only AND a SQLite authorizer
     denies anything other than reads, so even a bypass of (1) cannot write.
"""
from __future__ import annotations

import re
import sqlite3

ALLOWED_TABLES = {"fact_order_lines", "dim_product", "dim_customer", "dim_region", "dim_date"}
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex|truncate)\b",
    re.IGNORECASE,
)
MAX_ROWS = 1000


class UnsafeSQLError(ValueError):
    pass


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)
    return re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)


def validate_sql(sql: str, max_rows: int = MAX_ROWS) -> str:
    clean = _strip_comments(sql).strip().rstrip(";").strip()
    if not clean:
        raise UnsafeSQLError("Empty query")
    if ";" in clean:
        raise UnsafeSQLError("Only a single statement is allowed")
    if not re.match(r"^(select|with)\b", clean, re.IGNORECASE):
        raise UnsafeSQLError("Only SELECT queries are allowed")
    if FORBIDDEN.search(clean):
        raise UnsafeSQLError("Query contains a forbidden keyword")

    ctes = {m.lower() for m in re.findall(r"\b(\w+)\s+as\s*\(", clean, re.IGNORECASE)}
    referenced = {t.lower() for t in re.findall(r"\b(?:from|join)\s+([a-zA-Z_]\w*)", clean, re.IGNORECASE)}
    unknown = referenced - ALLOWED_TABLES - ctes
    if unknown:
        raise UnsafeSQLError(f"Table(s) not allowed: {', '.join(sorted(unknown))}")

    if not re.search(r"\blimit\s+\d+\s*$", clean, re.IGNORECASE):
        clean = f"{clean}\nLIMIT {max_rows}"
    return clean


def _read_only_authorizer(action, arg1, arg2, dbname, source):
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
    return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY


def read_only_connection(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
    con.set_authorizer(_read_only_authorizer)
    return con
