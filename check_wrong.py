import json
import sys
from pathlib import Path

folder = sys.argv[1] if len(sys.argv) > 1 else "results"

for name in ("baseline", "full"):
    path = Path(folder) / f"{name}.jsonl"
    if not path.exists():
        print(f"(no {path} yet, skipping)")
        continue

    print("=" * 30, name)
    graded = wrong = errored = 0

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if "gold_error" in r:          # gold SQL failed, so it cannot be graded
            continue
        graded += 1
        if r["final_ok"]:
            continue

        wrong += 1
        if r["final_error"]:
            errored += 1
        print("Q    :", r["question"])
        print("GOLD :", r["gold_sql"])
        print("PRED :", r["final_sql"])
        print("ERROR:", r["final_error"], "\n")

    ran_fine = wrong - errored
    pct = (wrong / graded * 100) if graded else 0
    print("-" * 30)
    print(f"{name}: {wrong} wrong out of {graded} graded ({pct:.1f}%)")
    print(f"   {errored} raised a database error (the correction loop can try to fix these)")
    print(f"   {ran_fine} ran fine but gave a wrong result (the loop cannot see these)\n")