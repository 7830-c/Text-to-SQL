import sqlite3
import sys
from pathlib import Path

path, words = Path(sys.argv[1]), [w.lower() for w in sys.argv[2:]]
c = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
c.text_factory = lambda b: b.decode("utf-8", errors="ignore")


def q(n):
    return '"' + n.replace('"', '""') + '"'


tables = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
for (t,) in tables:
    for _, col, typ, *_ in c.execute(f"PRAGMA table_info({q(t)})").fetchall():
        if not any(s in (typ or "").lower() for s in ("char", "text")):
            continue
        for w in words:
            try:
                n = c.execute(f"SELECT COUNT(*) FROM {q(t)} WHERE lower({q(col)}) LIKE ?", (f"%{w}%",)).fetchone()[0]
            except sqlite3.Error:
                continue
            if n:
                ex = [str(r[0])[:50] for r in c.execute(
                    f"SELECT DISTINCT {q(col)} FROM {q(t)} WHERE lower({q(col)}) LIKE ? LIMIT 3", (f"%{w}%",))]
                print(f"{w!r} -> {t}.{col}: {n} rows, e.g. {ex}")