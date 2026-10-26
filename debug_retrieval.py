import sys

from retriever import build_index, _embed_question

db, question = sys.argv[1], " ".join(sys.argv[2:])
b = build_index(db)
print(len(b["names"]), "tables in the database")
print("declared foreign keys:", sum(len(v["fks"]) for v in b["schema"].values()), "\n")

scores, ids = b["index"].search(_embed_question(question), 15)
for rank, (s, i) in enumerate(zip(scores[0], ids[0]), 1):
    print(f"{rank:2}. {s:.3f}  {b['names'][i]}")