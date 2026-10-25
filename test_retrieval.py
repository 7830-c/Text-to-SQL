from retriever import build_index, retrieve, format_schema

DB = "concert_singer"

bundle = build_index(DB)
print("Tables in DB:", bundle["names"])
print("\nExample embedded document:\n ", bundle["docs"][0])

questions = [
    "How many singers do we have?",
    "What are the names of concerts held in 2014?",
    "Show the names of singers who performed at the stadium with the largest capacity.",
]

for q in questions:
    r = retrieve(q, DB, k=2)
    print("\n" + "=" * 70)
    print("Q:", q)
    print("Top-k       :", r["top_k"], r["scores"])
    print("Added by FK :", r["added_by_fk"])
    print("Final tables:", r["tables"])

print("\n" + "=" * 70)
print("Schema text that would go into the LLM prompt (last question):\n")
print(format_schema(DB, r["tables"]))