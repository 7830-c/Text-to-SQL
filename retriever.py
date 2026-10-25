from functools import lru_cache

import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

from config import MODEL_NAME
from schema_utils import get_schema

_model = SentenceTransformer(MODEL_NAME)
_cache = {}  # db_id -> index bundle, so we build each index only once


def _embed(texts):
    """Texts -> normalized float32 vectors (so inner product == cosine similarity)."""
    v = _model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(v, dtype="float32")


@lru_cache(maxsize=None)
def _embed_question(question):
    return _embed([question])


def table_to_document(name, info):
    """Short natural-language description of one table, used for embedding."""
    parts = []
    for c in info["columns"]:
        text = c["name"].replace("_", " ")
        is_texty = any(s in (c["type"] or "").lower() for s in ("text", "char", "var"))
        vals = info["samples"].get(c["name"], [])
        if is_texty and vals:
            text += " (e.g. " + ", ".join(vals) + ")"
        parts.append(text)
    return f"table {name.replace('_', ' ')}: columns " + ", ".join(parts)


def build_index(db_id):
    """Build (or fetch from cache) a FAISS index over this database's tables."""
    if db_id in _cache:
        return _cache[db_id]

    schema = get_schema(db_id)
    names = list(schema.keys())  # position i in FAISS == names[i]
    docs = [table_to_document(n, schema[n]) for n in names]

    vecs = _embed(docs)
    index = faiss.IndexFlatIP(vecs.shape[1])
    index.add(vecs)

    _cache[db_id] = {"index": index, "names": names, "schema": schema, "docs": docs}
    return _cache[db_id]


def expand_with_fks(selected, schema):
    """
    Add tables the LLM will likely need for joins:
      1) tables referenced by a foreign key from a selected table
      2) 'bridge' tables whose FKs point to 2+ of the tables chosen so far
    """
    result = list(selected)
    for t in selected:
        for fk in schema[t]["fks"]:
            if fk["ref_table"] in schema and fk["ref_table"] not in result:
                result.append(fk["ref_table"])

    chosen = set(result)
    for t, info in schema.items():
        if t in chosen:
            continue
        targets = {fk["ref_table"] for fk in info["fks"]} & chosen
        if len(targets) >= 2:
            result.append(t)
    return result


def retrieve(question, db_id, k=3, use_fk_expansion=True):
    """Return the most relevant tables for a question."""
    bundle = build_index(db_id)
    k = min(k, len(bundle["names"]))

    scores, ids = bundle["index"].search(_embed_question(question), k)
    top = [bundle["names"][i] for i in ids[0]]

    final = expand_with_fks(top, bundle["schema"]) if use_fk_expansion else top
    return {
        "top_k": top,
        "scores": [round(float(s), 3) for s in scores[0]],
        "tables": final,
        "added_by_fk": [t for t in final if t not in top],
    }


def all_tables(db_id):
    """For the baseline run: every table, no retrieval."""
    return build_index(db_id)["names"]


def format_schema(db_id, tables):
    """Turn chosen tables into CREATE TABLE text to paste into the LLM prompt."""
    schema = build_index(db_id)["schema"]
    keep = set(tables)
    blocks = []
    for t in tables:
        info = schema[t]
        lines = [f'  "{c["name"]}" {c["type"] or "TEXT"}' for c in info["columns"]]

        pks = [c["name"] for c in info["columns"] if c["pk"]]
        if pks:
            lines.append("  PRIMARY KEY (" + ", ".join(f'"{p}"' for p in pks) + ")")

        for fk in info["fks"]:
            if fk["ref_table"] in keep:
                target = f' ("{fk["to"]}")' if fk["to"] else ""
                lines.append(
                    f'  FOREIGN KEY ("{fk["from"]}") REFERENCES "{fk["ref_table"]}"{target}'
                )
        blocks.append(f'CREATE TABLE "{t}" (\n' + ",\n".join(lines) + "\n);")
    return "\n\n".join(blocks)