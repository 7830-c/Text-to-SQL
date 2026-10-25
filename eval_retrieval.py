import json
import sqlglot
from sqlglot import exp

from config import SPIDER_DIR
from retriever import build_index, retrieve

LIMIT = None   # set e.g. LIMIT = 300 for a faster run
KS = [1, 2, 3, 4, 5]


def gold_tables(sql):
    """Table names used by the gold SQL (lowercase)."""
    tree = sqlglot.parse_one(sql, read="sqlite")
    return {t.name.lower() for t in tree.find_all(exp.Table)}


with open(f"{SPIDER_DIR}/dev.json", encoding="utf-8") as f:
    dev = json.load(f)
if LIMIT:
    dev = dev[:LIMIT]

# stats[(k, use_fk)] = lists of per-question numbers
stats = {(k, fk): {"rec": [], "full": [], "n": []} for k in KS for fk in (False, True)}
skipped = 0

for ex in dev:
    db_id, question = ex["db_id"], ex["question"]
    try:
        gold = gold_tables(ex["query"])
    except Exception:
        skipped += 1
        continue

    schema_names = {n.lower() for n in build_index(db_id)["names"]}
    gold &= schema_names
    if not gold:
        skipped += 1
        continue

    for k in KS:
        for fk in (False, True):
            r = retrieve(question, db_id, k=k, use_fk_expansion=fk)
            got = {t.lower() for t in r["tables"]}
            s = stats[(k, fk)]
            s["rec"].append(len(gold & got) / len(gold))
            s["full"].append(1.0 if gold <= got else 0.0)
            s["n"].append(len(got))

total = len(stats[(1, False)]["rec"])
print(f"Evaluated {total} questions ({skipped} skipped)\n")
print("Table recall = avg fraction of gold tables retrieved")
print("Full recall  = % of questions where ALL gold tables were retrieved\n")
print(f"{'k':>2} | {'recall':>7} {'full':>6} {'#tbl':>5} | {'recall+FK':>9} {'full+FK':>8} {'#tbl+FK':>8}")
print("-" * 62)


def avg(xs):
    return sum(xs) / len(xs)


for k in KS:
    a, b = stats[(k, False)], stats[(k, True)]
    print(
        f"{k:>2} | {avg(a['rec']):>7.3f} {avg(a['full']):>6.3f} {avg(a['n']):>5.1f} | "
        f"{avg(b['rec']):>9.3f} {avg(b['full']):>8.3f} {avg(b['n']):>8.1f}"
    )