import json
from config import SPIDER_DIR
from agent import run_agent
from executor import run_sql


def show(state):
    for h in state["history"]:
        print("  ", h)
    print("  FINAL SQL :", state["sql"])
    print("  ERROR     :", state["error"])
    print("  RETRIES   :", state["retry_count"])
    if state["result"] is not None:
        print("  ROWS      :", state["result"][:5])


# Test 1: the executor alone, with a deliberately wrong column name
print("=== Test 1: executor returns an error message instead of crashing ===")
rows, err = run_sql("concert_singer", "SELECT nme FROM singer")
print("rows:", rows, "| error:", err)

# Test 2: the executor refuses a dangerous query
print("\n=== Test 2: safety check ===")
print(run_sql("concert_singer", "DROP TABLE singer"))

# Test 3: watch the correction loop fix a broken query on purpose
print("\n=== Test 3: self-correction (starting from a broken query) ===")
state = run_agent(
    "How many singers do we have?", "concert_singer",
    seed_sql="SELECT COUNT(singer_name) FROM singers",
)
show(state)

# Test 4: normal runs on real Spider dev questions
print("\n=== Test 4: real dev questions ===")
dev = json.load(open(f"{SPIDER_DIR}/dev.json", encoding="utf-8"))
for ex in dev[:5]:
    print("\nQ:", ex["question"], f"[{ex['db_id']}]")
    state = run_agent(ex["question"], ex["db_id"])
    show(state)
    print("  GOLD SQL  :", ex["query"])