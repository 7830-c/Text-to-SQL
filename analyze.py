import csv
import json
import math
import random
from collections import Counter
from pathlib import Path

import config
from schema_utils import get_schema

R = Path(config.RESULTS_DIR)


def load(name):
    rows = {}
    for line in (R / f"{name}.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if "gold_error" not in r:
                rows[r["idx"]] = r
    return rows


base_all, full_all = load("baseline"), load("full")
common = sorted(set(base_all) & set(full_all))
base = [base_all[i] for i in common]
full = [full_all[i] for i in common]
n = len(common)
print(f"Questions graded in both runs: {n}\n")


def score(rows, key):
    p = sum(r[key] for r in rows) / n
    return p, 1.96 * math.sqrt(p * (1 - p) / n)      # approximate 95% margin of error


stages = [
    ("Baseline (all tables, no correction)", score(base, "final_ok")),
    ("+ Retrieval (first attempt)", score(full, "first_ok")),
    ("+ Self-correction (final answer)", score(full, "final_ok")),
]

print("EXECUTION ACCURACY")
for name, (p, m) in stages:
    print(f"  {name:40} {p*100:5.1f}%  (±{m*100:.1f})")
print("  Differences smaller than the ± margin may just be noise.\n")

gain = sum(1 for b, f in zip(base, full) if not b["final_ok"] and f["final_ok"])
loss = sum(1 for b, f in zip(base, full) if b["final_ok"] and not f["final_ok"])
print(f"Baseline vs final system: {gain} questions gained, {loss} lost\n")

# What did the correction loop do?
errored = [r for r in full if r["first_error"]]
recovered = [r for r in errored if not r["final_error"]]
fixed_right = [r for r in errored if r["final_ok"]]
print("SELF-CORRECTION")
print(f"  First attempt raised a DB error:     {len(errored)}")
print(f"  Ran without error after correction:  {len(recovered)}")
print(f"  ...and also gave the correct answer: {len(fixed_right)}")
print("  The loop can only fix queries that raise errors; it cannot catch a query that runs but is wrong.\n")


def category(err):
    e = err.lower()
    if "no such column" in e:
        return "no such column"
    if "no such table" in e:
        return "no such table"
    if "syntax error" in e:
        return "syntax error"
    if "ambiguous" in e:
        return "ambiguous column"
    return "other error"


print("FIRST-ATTEMPT ERRORS BY TYPE")
for k, v in Counter(category(r["first_error"]) for r in errored).most_common():
    print(f"  {k:20} {v}")

final_wrong = [r for r in full if not r["final_ok"]]
cats = Counter(category(r["final_error"]) if r["final_error"] else "ran fine, wrong result"
               for r in final_wrong)
print("\nFINAL FAILURES BY TYPE")
for k, v in cats.most_common():
    print(f"  {k:24} {v}")

# Retrieval: prompt-size reduction
sizes = {}
total = reduced = 0
for r in full:
    sizes.setdefault(r["db_id"], len(get_schema(r["db_id"])))
    total += sizes[r["db_id"]]
    reduced += len(r["tables"])
print(f"\nRETRIEVAL: {reduced/n:.1f} tables sent on average, out of {total/n:.1f} in the database "
      f"({(1 - reduced/total)*100:.0f}% fewer)")

# A sheet for labeling the 'ran fine, wrong result' failures by hand
wrong_but_ran = [r for r in final_wrong if not r["final_error"]]
random.Random(1).shuffle(wrong_but_ran)
with open(R / "to_label.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["idx", "db_id", "question", "gold_sql", "final_sql", "category"])
    for r in wrong_but_ran[:50]:
        w.writerow([r["idx"], r["db_id"], r["question"], r["gold_sql"], r["final_sql"], ""])
print(f"\nWrote {R/'to_label.csv'}: fill the 'category' column "
      "(wrong table / wrong column / bad join / wrong aggregation / wrong filter / other).")

# Chart
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    names = ["Baseline", "+ Retrieval", "+ Self-correction"]
    vals = [p * 100 for _, (p, _) in stages]
    errs = [m * 100 for _, (_, m) in stages]
    plt.figure(figsize=(6, 4))
    bars = plt.bar(names, vals, yerr=errs, capsize=5, color=["#9aa5b1", "#5b8def", "#2e9e6b"])
    for b, v in zip(bars, vals):
        plt.text(b.get_x() + b.get_width() / 2, v + 1, f"{v:.1f}%", ha="center")
    plt.ylabel("Execution accuracy (%)")
    plt.ylim(0, 105)
    plt.title(f"Text-to-SQL ablation (n={n})")
    plt.tight_layout()
    plt.savefig(R / "ablation.png", dpi=150)
    print(f"Saved chart: {R/'ablation.png'}")
except ImportError:
    print("pip install matplotlib to get the chart")