import sqlite3
from pathlib import Path
from config import SPIDER_DIR, UPLOAD_DIR

def get_db_path(db_id):
    if db_id.startswith("upload_"):
        return Path(UPLOAD_DIR) / f"{db_id}.sqlite"
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

    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
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

        # Big database with almost no declared keys: guess links such as user_id -> accounts_user.id
    declared = sum(len(v["fks"]) for v in schema.values())
    if len(names) > 30 and declared < len(names) // 10:
        by_key = {}
        for t in names:
            low = t.lower()
            by_key.setdefault(low, set()).add(t)
            if "_" in low:
                by_key.setdefault(low.split("_", 1)[1], set()).add(t)
        for t, info in schema.items():
            have = {fk["from"].lower() for fk in info["fks"]}
            for col in info["columns"]:
                name = col["name"].lower()
                if not name.endswith("_id") or name == "id" or name in have:
                    continue
                targets = by_key.get(name[:-3], set())
                if len(targets) != 1:
                    continue                      # no match, or ambiguous: skip
                target = next(iter(targets))
                if target != t and any(c["name"].lower() == "id" for c in schema[target]["columns"]):
                    info["fks"].append({"from": col["name"], "ref_table": target,
                                        "to": "id", "inferred": True})
    
    conn.close()
    return schema


if __name__ == "__main__":
    import pprint
    pprint.pprint(get_schema("concert_singer"))