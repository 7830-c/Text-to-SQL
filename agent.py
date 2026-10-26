import re
import time
from typing import TypedDict, Optional, List, Any

from langgraph.graph import StateGraph, START, END

from llm import ask_llm, clean_sql
from prompts import GENERATOR_PROMPT, CORRECTOR_PROMPT, PICKER_PROMPT
from executor import run_sql
from retriever import retrieve, all_tables, format_schema, build_index, expand_with_fks


class AgentState(TypedDict):
    question: str
    db_id: str
    schema_text: str
    tables: List[str]
    sql: str
    result: Optional[List[Any]]
    error: Optional[str]
    retry_count: int
    history: List[dict]


def pick_tables_llm(question, db_id, provider=None, api_key=None, max_tables=6, info=None):
    """Show the model a compact catalog (table + column names) and let it choose the tables."""
    schema = build_index(db_id)["schema"]
    lines = []
    for t, tinfo in schema.items():
        cols = ", ".join(c["name"] for c in tinfo["columns"][:25])
        tag = " [empty]" if tinfo.get("rows") == 0 else ""
        lines.append(f"{t}{tag}({cols})")
    prompt = PICKER_PROMPT.format(n=max_tables, question=question, catalog="\n".join(lines))
    answer = ask_llm(prompt, provider=provider, api_key=api_key, info=info)
    wanted = {w.strip(" `\"'*-.").lower() for w in re.split(r"[,\n]", answer)}
    picked = [t for t in schema if t.lower() in wanted][:max_tables]
    return picked, answer, prompt


def build_graph(use_retrieval=True, max_retries=3, k=3, provider=None, api_key=None, picker=False):
    def retrieve_schema(state):
        t0 = time.time()
        schema = build_index(state["db_id"])["schema"]
        entry = {"step": "retrieve_schema", "total_tables": len(schema)}

        if use_retrieval and picker:
            info = {}
            picked, raw, prompt = pick_tables_llm(state["question"], state["db_id"],
                                                  provider, api_key, info=info)
            if picked:
                tables = expand_with_fks(picked, schema)
                entry.update(method="LLM table picker", picked=picked,
                             added_by_fk=[t for t in tables if t not in picked])
            else:   # the model returned nothing usable: fall back to embedding search
                r = retrieve(state["question"], state["db_id"], k=k)
                tables = r["tables"]
                entry.update(method="embedding search (the picker returned nothing usable)",
                             scores=dict(zip(r["top_k"], r["scores"])),
                             added_by_fk=r["added_by_fk"])
            entry.update(llm=info, raw_answer=raw, prompt=prompt)
        elif use_retrieval:
            r = retrieve(state["question"], state["db_id"], k=k)
            tables = r["tables"]
            entry.update(method="embedding search", scores=dict(zip(r["top_k"], r["scores"])),
                         added_by_fk=r["added_by_fk"])
        else:
            tables = all_tables(state["db_id"])
            entry.update(method="all tables (small database, no retrieval needed)")

        schema_text = format_schema(state["db_id"], tables)
        entry.update(tables=tables, seconds=round(time.time() - t0, 2))
        return {"schema_text": schema_text, "tables": tables,
                "history": state["history"] + [entry]}

    def generate(state):
        t0 = time.time()
        if state["sql"]:   # a SQL was supplied for testing; use it instead of asking the LLM
            sql = state["sql"]
            entry = {"step": "generate", "sql": sql, "seconds": 0.0,
                     "note": "SQL was supplied directly, no model call."}
        else:
            prompt = GENERATOR_PROMPT.format(
                schema=state["schema_text"], question=state["question"])
            info = {}
            sql = clean_sql(ask_llm(prompt, provider=provider, api_key=api_key, info=info))
            entry = {"step": "generate", "sql": sql, "prompt": prompt, "llm": info,
                     "seconds": round(time.time() - t0, 2)}
        return {"sql": sql, "history": state["history"] + [entry]}

    def execute(state):
        t0 = time.time()
        rows, error = run_sql(state["db_id"], state["sql"])
        entry = {"step": "execute", "ok": error is None, "error": error,
                 "rows": None if rows is None else len(rows),
                 "seconds": round(time.time() - t0, 2)}
        return {"result": rows, "error": error, "history": state["history"] + [entry]}

    def correct(state):
        t0 = time.time()
        prompt = CORRECTOR_PROMPT.format(
            schema=state["schema_text"], question=state["question"],
            sql=state["sql"], error=state["error"])
        info = {}
        new_sql = clean_sql(ask_llm(prompt, provider=provider, api_key=api_key, info=info))
        entry = {"step": "correct", "sql": new_sql, "attempt": state["retry_count"] + 1,
                 "failed_sql": state["sql"], "failed_error": state["error"],
                 "prompt": prompt, "llm": info, "seconds": round(time.time() - t0, 2)}
        return {"sql": new_sql, "retry_count": state["retry_count"] + 1,
                "history": state["history"] + [entry]}

    def route(state):
        if state["error"] is None:
            return "done"
        if state["retry_count"] >= max_retries:
            return "done"
        return "fix"

    g = StateGraph(AgentState)
    g.add_node("retrieve_schema", retrieve_schema)
    g.add_node("generate", generate)
    g.add_node("execute", execute)
    g.add_node("correct", correct)

    g.add_edge(START, "retrieve_schema")
    g.add_edge("retrieve_schema", "generate")
    g.add_edge("generate", "execute")
    g.add_conditional_edges("execute", route, {"done": END, "fix": "correct"})
    g.add_edge("correct", "execute")
    return g.compile()


def _start_state(question, db_id, seed_sql=""):
    return {"question": question, "db_id": db_id, "schema_text": "", "tables": [],
            "sql": seed_sql, "result": None, "error": None,
            "retry_count": 0, "history": []}


def run_agent(question, db_id, use_retrieval=True, max_retries=3, k=3,
              seed_sql="", provider=None, api_key=None):
    app = build_graph(use_retrieval, max_retries, k, provider, api_key)
    return app.invoke(_start_state(question, db_id, seed_sql))


def stream_agent(question, db_id, use_retrieval=True, max_retries=3, k=3,
                 provider=None, api_key=None, picker=False):
    """For the UI: yields (node_name, update) as each step finishes."""
    app = build_graph(use_retrieval, max_retries, k, provider, api_key, picker)
    for chunk in app.stream(_start_state(question, db_id), stream_mode="updates"):
        for node, update in chunk.items():
            yield node, update