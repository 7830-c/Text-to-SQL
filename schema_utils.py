import sqlite3
from pathlib import Path
from config import SPIDER_DIR


def get_db_path(db_id):
    return Path(SPIDER_DIR) / "database" / db_id / f"{db_id}.sqlite"


def _q(name):
    """Safely quote a table/column name for SQL."""
    return '"' + name.replace('"', '""') + '"'


def get_schema(db_id, n_samples=3):
    """
    Read a Spider SQLite database and return its schema as a dict:
    {
      table_name: {
        "columns": [{"name":..., "type":..., "pk": 0/1/2..}, ...],
        "fks":     [{"from": col, "ref_table": table, "to": col}, ...],
        "samples": {col_name: ["value1", "value2", ...]},
      }
    }
    """
    path = get_db_path(db_id)
    if not path.exists():
        raise FileNotFoundError(
            f"Database not found: {path}\nCheck SPIDER_DIR in config.py"
        )

    conn = sqlite3.connect(str(path))
    conn.text_factory = lambda b: b.decode("utf-8", errors="ignore")
    cur = conn.cursor()

    names = [
        r[0]
        for r in cur.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]
    lookup = {n.lower(): n for n in names}  # fix case mismatches in FK targets

    schema = {}
    for t in names:
        # PRAGMA table_info -> (cid, name, type, notnull, default, pk)
        cols = [
            {"name": r[1], "type": r[2], "pk": r[5]}
            for r in cur.execute(f"PRAGMA table_info({_q(t)})").fetchall()
        ]

        # PRAGMA foreign_key_list -> (id, seq, ref_table, from, to, ...)
        fks = []
        for r in cur.execute(f"PRAGMA foreign_key_list({_q(t)})").fetchall():
            fks.append(
                {"from": r[3], "ref_table": lookup.get(r[2].lower(), r[2]), "to": r[4]}
            )

        samples = {}
        for c in cols:
            try:
                rows = cur.execute(
                    f"SELECT DISTINCT {_q(c['name'])} FROM {_q(t)} "
                    f"WHERE {_q(c['name'])} IS NOT NULL LIMIT {n_samples}"
                ).fetchall()
                samples[c["name"]] = [str(x[0])[:25] for x in rows]
            except sqlite3.Error:
                samples[c["name"]] = []

        schema[t] = {"columns": cols, "fks": fks, "samples": samples}

    conn.close()
    return schema


if __name__ == "__main__":
    import pprint
    pprint.pprint(get_schema("concert_singer"))