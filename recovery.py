import sqlite3

import sqlglot
from sqlglot import exp

from retriever import build_index
from schema_utils import get_db_path

RULES = """

Matching rules:
- In SQLite, = on text is case sensitive. When filtering on text a person typed (names, cities, titles), compare case-insensitively, for example LOWER(col) = LOWER('value'), or use LIKE.
- If a full name is given and the table has separate first-name and last-name columns, filter each part separately instead of comparing the full name to one column.
- Join tables on matching ID columns (for example student.user_id = user.id) even when no foreign key is declared."""


def _q(name):
    return '"' + name.replace('"', '""') + '"'


def relax(sql):
    """Make text equality ignore capitalization and surrounding spaces. Returns (new_sql, changed)."""
    try:
        tree = sqlglot.parse_one(sql, read="sqlite")
    except Exception:
        return sql, False
    changed = []

    def fold(col):
        return exp.Lower(this=exp.Trim(this=col.copy()))

    def rewrite(node):
        if isinstance(node, exp.EQ):
            a, b = node.this, node.expression
            if isinstance(a, exp.Literal) and isinstance(b, exp.Column):
                a, b = b, a
            if isinstance(a, exp.Column) and isinstance(b, exp.Literal) and b.is_string:
                changed.append(1)
                return exp.EQ(this=fold(a), expression=exp.Literal.string(b.name.strip().lower()))
        if (isinstance(node, exp.In) and isinstance(node.this, exp.Column) and node.expressions
                and all(isinstance(e, exp.Literal) and e.is_string for e in node.expressions)):
            changed.append(1)
            return exp.In(this=fold(node.this),
                          expressions=[exp.Literal.string(e.name.strip().lower()) for e in node.expressions])
        return node

    new = tree.transform(rewrite)
    if not changed:
        return sql, False
    return new.sql(dialect="sqlite"), True


def literal_filters(db_id, sql):
    """Find (table, column, text) for each text filter in the query."""
    try:
        tree = sqlglot.parse_one(sql, read="sqlite")
    except Exception:
        return []
    schema = build_index(db_id)["schema"]
    cols_of = {t.lower(): {c["name"].lower(): c["name"] for c in info["columns"]}
               for t, info in schema.items()}
    real = {t.lower(): t for t in schema}
    alias = {(t.alias or t.name).lower(): t.name.lower() for t in tree.find_all(exp.Table)}

    found, seen = [], set()
    for node in tree.find_all(exp.EQ, exp.Like):
        col, lit = node.this, node.expression
        if isinstance(col, exp.Literal) and isinstance(lit, exp.Column):
            col, lit = lit, col
        if not (isinstance(col, exp.Column) and isinstance(lit, exp.Literal) and lit.is_string):
            continue
        cname = col.name.lower()
        if col.table:
            tables = [alias.get(col.table.lower(), col.table.lower())]
        else:
            tables = [t for t in set(alias.values()) if cname in cols_of.get(t, {})]
        for t in tables:
            if t in cols_of and cname in cols_of[t] and (t, cname, lit.name) not in seen:
                seen.add((t, cname, lit.name))
                found.append((real[t], cols_of[t][cname], lit.name))
    return found[:4]


def evidence(db_id, filters, look):
    """What the data shows about each filter. Reads real values only when `look` is True."""
    lines = []
    if not look:
        return [f"- {t}.{c} was compared with '{lit}'." for t, c, lit in filters]

    path = get_db_path(db_id).resolve()
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    conn.text_factory = lambda b: b.decode("utf-8", errors="ignore")

    def fetch(sql, args=()):
        return [str(r[0])[:40] for r in conn.execute(sql, args).fetchall()]

    try:
        for t, c, lit in filters:
            core, col, tab = lit.strip("%").strip(), _q(c), _q(t)
            try:
                same = fetch(f"SELECT DISTINCT {col} FROM {tab} WHERE lower(trim({col})) = lower(?) LIMIT 3", (core,))
                if same:
                    lines.append(f"- {t}.{c}: stored spelling matching '{lit}' ignoring case: "
                                 + ", ".join(f"'{v}'" for v in same))
                    continue
                part = fetch(f"SELECT DISTINCT {col} FROM {tab} WHERE lower({col}) LIKE ? LIMIT 3", (f"%{core.lower()}%",))
                if part:
                    lines.append(f"- {t}.{c}: values containing '{core}': " + ", ".join(f"'{v}'" for v in part))
                    continue
                sample = fetch(f"SELECT DISTINCT {col} FROM {tab} WHERE {col} IS NOT NULL LIMIT 5")
                msg = f"- {t}.{c}: no value contains '{core}'. Example values in this column: " + ", ".join(f"'{v}'" for v in sample)
                if " " in core:
                    msg += ". The text has several words, so the parts may be stored in separate columns."
                lines.append(msg)
            except sqlite3.Error:
                lines.append(f"- {t}.{c} was compared with '{lit}'.")
    finally:
        conn.close()
    return lines


def soft_message(tried_relaxed, lines):
    msg = "The query ran without any database error but returned 0 rows."
    if tried_relaxed:
        msg += " A version with case-insensitive, whitespace-trimmed text comparisons also returned 0 rows."
    msg += (" This usually means a filter does not match how the data is stored (capitalization, spacing, "
            "a name split across first-name and last-name columns, the wrong column or table), "
            "or a condition is too strict.")
    if lines:
        msg += "\nWhat the data shows:\n" + "\n".join(lines)
    msg += "\nRewrite the query so it is more likely to match. If the question really has no matching rows, return the same query."
    return msg