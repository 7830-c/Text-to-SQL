import re
import sqlite3
import time

from retriever import build_index
from schema_utils import get_db_path

# Columns that are personal, secret, or long free text are never read
SKIP_COL = re.compile(
    r"email|phone|password|token|hash|otp|secret|key|url|link|photo|image|file|path|address|"
    r"first_name|last_name|username|bio|remarks|notes|description|message|body|content|data|json", re.I)
STOP = set("""the and for with that this from have has are was were who whom whose which what when where give show list get
all any each every me my our their his her its into about than then them they there these those also only just like want need
please tell names name students student users user profile profiles detail details role status cohort cohorts record records
starts start starting enrolled number total count how many much more most less least find display fetch""".split())

_enum_cache = {}   # (db_id, table) -> {column: [values]}


def _q(n):
    return '"' + n.replace('"', '""') + '"'


def _text_cols(info):
    return [c["name"] for c in info["columns"]
            if any(s in (c["type"] or "").lower() for s in ("char", "text")) and not SKIP_COL.search(c["name"])]


def _enum_values(conn, db_id, table, info):
    """Columns with at most 12 distinct values, computed once per table."""
    key = (db_id, table)
    if key not in _enum_cache:
        found = {}
        for col in _text_cols(info):
            try:
                vals = [str(r[0])[:40] for r in conn.execute(
                    f"SELECT DISTINCT {_q(col)} FROM {_q(table)} "
                    f"WHERE {_q(col)} IS NOT NULL AND {_q(col)} <> '' LIMIT 13")]
            except sqlite3.Error:
                continue
            if 0 < len(vals) <= 12:
                found[col] = vals
        _enum_cache[key] = found
    return _enum_cache[key]


def _tokens(question):
    out = []
    for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9_.\-]*", question):
        w = w.strip("-_.").lower()
        if len(w) >= 3 and w not in STOP and w not in out:
            out.append(w)
    return out[:8]


def data_notes(db_id, question, tables, budget_s=6.0):
    """Returns (text for the prompt, details for the report). Reads real values, locally."""
    schema = build_index(db_id)["schema"]
    tables = [t for t in tables if t in schema]
    path = get_db_path(db_id).resolve()
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    conn.text_factory = lambda b: b.decode("utf-8", errors="ignore")
    toks, found, enum_lines, timed_out = _tokens(question), [], [], False
    t0 = time.time()
    try:
        for t in tables:
            info = schema[t]
            rows = info.get("rows", 1000)
            if rows < 20 or rows > 200000:
                continue
            for col, vals in _enum_values(conn, db_id, t, info).items():
                enum_lines.append(f"- {t}.{col}: " + ", ".join(f"'{v}'" for v in vals))

        for t in tables:
            if not toks:
                break
            info = schema[t]
            if info.get("rows", 1000) > 200000:
                continue
            for col in _text_cols(info):
                if time.time() - t0 > budget_s:
                    timed_out = True
                    break
                where = " OR ".join(f"lower({_q(col)}) LIKE ?" for _ in toks)
                try:
                    hits = conn.execute(f"SELECT DISTINCT {_q(col)} FROM {_q(t)} WHERE {where} LIMIT 4",
                                        [f"%{w}%" for w in toks]).fetchall()
                except sqlite3.Error:
                    continue
                if hits:
                    found.append(f"- {t}.{col} contains: " + ", ".join(f"'{str(r[0])[:50]}'" for r in hits))
            if timed_out:
                break
    finally:
        conn.close()

    parts = []
    if found:
        parts.append("Words from the question found in the stored data (use these exact spellings; "
                     "use LIKE '%word%' when a code may have a prefix or suffix):\n" + "\n".join(found[:15]))
    if enum_lines:
        parts.append("Columns that hold only a few distinct values:\n" + "\n".join(enum_lines[:40]))
    detail = {"words": toks, "found": found[:15], "enum_columns": len(enum_lines), "timed_out": timed_out}
    return "\n\n".join(parts), detail