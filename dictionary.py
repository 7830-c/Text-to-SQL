import datetime
import hashlib
import json
import re
from pathlib import Path

import config
from llm import ask_llm
from prompts import DICT_BATCH_PROMPT, DICT_OVERVIEW_PROMPT
from schema_utils import get_schema

_store = {}   # db_id -> overview, held in memory
_sig = {}     # db_id -> (schema signature, number of tables)


def _signature(db_id):
    """Hash of table and column names, so the same schema reuses the same overview."""
    if db_id not in _sig:
        schema = get_schema(db_id, n_samples=0)
        text = "|".join(
            f"{t}:" + ",".join(f"{c['name']} {c['type'] or ''}" for c in info["columns"])
            for t, info in sorted(schema.items())
        )
        _sig[db_id] = (hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16], len(schema))
    return _sig[db_id]


def table_count(db_id):
    return _signature(db_id)[1]


def _path(db_id):
    prefix = "private_" if db_id.startswith("upload_") else ""   # easy to keep out of Git
    return Path(config.DICT_DIR) / f"{prefix}{_signature(db_id)[0]}.json"


def get(db_id):
    return _store.get(db_id)


def load_cached(db_id):
    """Overview from memory, else from disk, else None."""
    if db_id in _store:
        return _store[db_id]
    try:
        p = _path(db_id)
        if p.exists():
            _store[db_id] = json.loads(p.read_text(encoding="utf-8"))
            return _store[db_id]
    except Exception:
        pass
    return None


def forget(db_id, delete_disk=False):
    if delete_disk:
        try:
            _path(db_id).unlink(missing_ok=True)
        except Exception:
            pass
    _store.pop(db_id, None)
    _sig.pop(db_id, None)


def _parse_json(text):
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def build(db_id, provider=None, api_key=None, progress=None, persist=True):
    """Describe every table (batches of DICT_BATCH_TABLES), then write the overview."""
    schema = get_schema(db_id, n_samples=0)
    names = list(schema)
    size = max(config.DICT_BATCH_TABLES, 1)
    batches = [names[i:i + size] for i in range(0, len(names), size)]
    total = len(batches) + 1
    lower = {n.lower(): n for n in names}
    descs, notes, failed, last = {}, [], 0, {}

    for i, batch in enumerate(batches):
        if progress:
            progress(i, total, f"Describing tables {i * size + 1} to {min((i + 1) * size, len(names))} of {len(names)}")
        lines = []
        for t in batch:
            info = schema[t]
            cols = ", ".join(f"{c['name']}:{(c['type'] or 'any').lower()[:14]}" for c in info["columns"][:30])
            tag = " [empty]" if info.get("rows") == 0 else ""
            lines.append(f"{t}{tag}({cols})")
        try:
            raw = ask_llm(DICT_BATCH_PROMPT.format(catalog="\n".join(lines)),
                          provider=provider, api_key=api_key, info=last)
        except Exception:
            if i == 0:
                raise               # a bad key or model id: stop now instead of failing 12 more times
            failed += 1
            continue
        data = _parse_json(raw) or {}
        if not isinstance(data.get("tables"), dict):
            failed += 1
            continue
        for k, v in data["tables"].items():
            real = lower.get(str(k).strip().lower())
            if real and isinstance(v, str) and v.strip():
                descs[real] = v.strip()[:200]
        if isinstance(data.get("notes"), list):
            notes += [n.strip()[:200] for n in data["notes"] if isinstance(n, str) and n.strip()]

    notes = list(dict.fromkeys(notes))[:12]

    if progress:
        progress(len(batches), total, "Writing the overview")
    overview, areas = "", []
    lines = [f"{t}: {descs[t]}" for t in names if t in descs][:300]
    if lines:
        try:
            raw = ask_llm(DICT_OVERVIEW_PROMPT.format(lines="\n".join(lines)),
                          provider=provider, api_key=api_key, info=last)
            data = _parse_json(raw) or {}
            overview = str(data.get("overview", "")).strip()
            if isinstance(data.get("areas"), list):
                areas = [a.strip() for a in data["areas"] if isinstance(a, str) and a.strip()][:8]
        except Exception:
            pass

    d = {"overview": overview, "areas": areas, "notes": notes, "tables": descs,
         "n_tables": len(names), "failed_batches": failed,
         "model": last.get("model", ""), "created": datetime.date.today().isoformat()}
    _store[db_id] = d
    if persist:
        try:
            p = _path(db_id)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(d, indent=1), encoding="utf-8")
        except Exception:
            pass
    if progress:
        progress(total, total, "Done")
    return d


def context_for(db_id, tables):
    """Text added to the SQL prompt: overview, notes, and descriptions of the chosen tables only."""
    d = _store.get(db_id)
    if not d:
        return ""
    parts = []
    if d.get("overview"):
        parts.append("Background about this database (generated, may be imperfect): " + d["overview"])
    if d.get("notes"):
        parts.append("Notes:\n" + "\n".join("- " + n for n in d["notes"][:10]))
    descs = [f"- {t}: {d['tables'][t]}" for t in tables if d["tables"].get(t)]
    if descs:
        parts.append("What the tables above hold:\n" + "\n".join(descs))
    return ("\n\n" + "\n\n".join(parts)) if parts else ""