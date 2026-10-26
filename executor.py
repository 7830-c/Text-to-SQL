import sqlite3
import time

import sqlglot
from sqlglot import exp

from schema_utils import get_db_path

SET_OPS = tuple(c for c in (getattr(exp, "SetOperation", None), exp.Union) if c)
FORBIDDEN = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create)


def check_safe(sql):
    """Return an error message if the SQL is not a plain read query, else None."""
    try:
        tree = sqlglot.parse_one(sql, read="sqlite")
    except Exception:
        return None  # can't parse? let SQLite run it and give its own error message
    if tree is None:
        return "Empty query."
    if not isinstance(tree, (exp.Select,) + SET_OPS):
        return "Only SELECT queries are allowed."
    if tree.find(*FORBIDDEN):
        return "Query contains a data-changing statement, which is not allowed."
    return None


def run_sql(db_id, sql, timeout_s=30):
    """
    Returns (rows, error). Exactly one of them is None.
    Errors are returned as text instead of raised, so the agent can learn from them.
    """
    problem = check_safe(sql)
    if problem:
        return None, problem

    path = get_db_path(db_id).resolve()
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)  # read-only
    conn.text_factory = lambda b: b.decode("utf-8", errors="ignore")

    deadline = time.time() + timeout_s
    conn.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 10000)

    try:
        rows = conn.execute(sql).fetchall()
        return rows, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    finally:
        conn.close()
        
        
def preview_sql(db_id, sql, limit=200, timeout_s=30):
    """For the UI. Returns (column_names, rows, has_more, error), same safety rules as run_sql."""
    problem = check_safe(sql)
    if problem:
        return None, None, False, problem

    path = get_db_path(db_id).resolve()
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    conn.text_factory = lambda b: b.decode("utf-8", errors="ignore")
    deadline = time.time() + timeout_s
    conn.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 10000)
    try:
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(limit + 1)
        return cols, rows[:limit], len(rows) > limit, None
    except Exception as e:
        return None, None, False, f"{type(e).__name__}: {e}"
    finally:
        conn.close()