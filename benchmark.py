import json
import random
import sys
from pathlib import Path

import config
import llm
from agent import run_agent
from compare import same_result
from executor import run_sql

mode = sys.argv[1] if len(sys.argv) > 1 else ""
if mode not in ("baseline", "full"):
    sys.exit("Usage:  python benchmark.py baseline    or    python benchmark.py full")

use_retrieval = (mode == "full")
max_retries = config.MAX_RETRIES if mode == "full" else 0

# The same fixed random subset every time, so both runs see identical questions
dev = json.load(open(f"{config.SPIDER_DIR}/dev.json", encoding="utf-8"))
subset = random.Random(config.BENCH_SEED).sample(range(len(dev)), config.BENCH_N)

out_dir = Path(config.RESULTS_DIR)
out_dir.mkdir(exist_ok=True)
out_file = out_dir / f"{mode}.jsonl"

provider = config.LLM_CHAIN[0]
(out_dir / "meta.json").write_text(json.dumps({
    "chain": config.LLM_CHAIN, "model": config.model_of(provider),
    "n": config.BENCH_N, "seed": config.BENCH_SEED, "k": config.RETRIEVAL_K,
    "max_retries": config.MAX_RETRIES}, indent=2))
if len(config.LLM_CHAIN) > 1:
    print("WARNING: LLM_CHAIN has a backup model. Set LLM_CHAIN=google for a clean benchmark.\n")

# Resume support: skip questions already saved
done = set()
if out_file.exists():
    for line in out_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            done.add(json.loads(line)["idx"])
print(f"Mode: {mode} | model: {config.model_of(provider)} | "
      f"questions: {len(subset)} | already done: {len(done)}\n")

with open(out_file, "a", encoding="utf-8") as f:
    for n, idx in enumerate(subset, 1):
        if idx in done:
            continue
        ex = dev[idx]

        gold_rows, gold_err = run_sql(ex["db_id"], ex["query"])
        if gold_err:                                   # cannot grade without a valid gold result
            f.write(json.dumps({"idx": idx, "gold_error": gold_err}) + "\n")
            f.flush()
            print(f"[{n}/{len(subset)}] skipped (gold SQL failed)")
            continue

        try:
            state = run_agent(ex["question"], ex["db_id"], use_retrieval=use_retrieval,
                              max_retries=max_retries, k=config.RETRIEVAL_K)
        except Exception as e:
            print(f"\nStopped at question {n}: {e}")
            print("Progress is saved. Run the same command again to resume.")
            break

        # The first SQL the model wrote, before any correction
        first_sql = next(h["sql"] for h in state["history"] if h["step"] == "generate")
        first_rows, first_err = run_sql(ex["db_id"], first_sql)

        rec = {
            "idx": idx, "db_id": ex["db_id"], "question": ex["question"],
            "gold_sql": ex["query"], "tables": state["tables"],
            "first_sql": first_sql, "first_error": first_err,
            "first_ok": same_result(first_rows, gold_rows, ex["query"]),
            "final_sql": state["sql"], "final_error": state["error"],
            "final_ok": same_result(state["result"], gold_rows, ex["query"]),
            "retries": state["retry_count"],
        }
        f.write(json.dumps(rec) + "\n")
        f.flush()                                       # saved after every question
        print(f"[{n}/{len(subset)}] {'OK   ' if rec['final_ok'] else 'WRONG'} retries={rec['retries']}")

print("\nLLM calls this session:", llm.calls)