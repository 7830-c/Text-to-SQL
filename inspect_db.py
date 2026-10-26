import hashlib
import sqlite3
import sys
from pathlib import Path

if len(sys.argv) < 2:
    sys.exit("Usage: python inspect_db.py <path to .sqlite file> [keyword ...]")

path = Path(sys.argv[1])
keywords = [w.lower() for w in sys.argv[2:]]


def q(name):
    return '"' + name.replace('"', '""') + '"'


print("file  :", path)
print("size  :", round(path.stat().st_size / 1e6, 2), "MB")
print("sha256:", hashlib.sha256(path.read_bytes()).hexdigest()[:16])

c = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
c.text_factory = lambda b: b.decode("utf-8", errors="ignore")

objects = c.execute("SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
tables = sorted(n for t, n in objects if t == "table")
views = sorted(n for t, n in objects if t == "view")

info, total_cols, total_rows, total_fks = [], 0, 0, 0
for t in tables:
    cols = [r[1] for r in c.execute(f"PRAGMA table_info({q(t)})")]
    fks = c.execute(f"PRAGMA foreign_key_list({q(t)})").fetchall()
    n = c.execute(f"SELECT COUNT(*) FROM {q(t)}").fetchone()[0]
    info.append((t, cols, n, len(fks)))
    total_cols += len(cols)
    total_rows += n
    total_fks += len(fks)

print("\n=== SUMMARY ===")
print("tables               :", len(tables))
print("views                :", len(views), "(the app ignores views)")
print("total columns        :", total_cols)
print("total rows           :", total_rows)
print("declared foreign keys:", total_fks)
print("empty tables         :", sum(1 for _, _, n, _ in info if n == 0))

print("\n=== TABLES ===")
print(f"{'#':>3}  {'table':45} {'cols':>5} {'rows':>9} {'fks':>4}")
for i, (t, cols, n, f) in enumerate(info, 1):
    print(f"{i:>3}  {t[:45]:45} {len(cols):>5} {n:>9} {f:>4}")

if keywords:
    print("\n=== COLUMNS MATCHING", keywords, "===")
    for t, cols, n, _ in info:
        hits = [col for col in cols if any(k in col.lower() for k in keywords)]
        if hits:
            print(f"{t} ({n} rows): {', '.join(hits)}")