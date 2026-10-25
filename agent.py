from typing import TypedDict, Optional, List, Any

from langgraph.graph import StateGraph, START, END

from llm import ask_llm, clean_sql
from prompts import GENERATOR_PROMPT, CORRECTOR_PROMPT
from executor import run_sql
from retriever import retrieve, all_tables, format_schema


class AgentState(TypedDict):
    question: str
    db_id: str
    schema_text: str
    tables: List[str]
    sql: str
    result: Optional[List[Any]]
    error: Optional[str]
    retry_count: int
    history: List[dict]   # step-by-step trace, used for the UI and error analysis


def build_graph(use_retrieval=True, max_retries=3, k=3):
    """
    One graph, three experiments:
      baseline        -> use_retrieval=False, max_retries=0
      + retrieval     -> use_retrieval=True,  max_retries=0
      + self-correct  -> use_retrieval=True,  max_retries=3
    """

    def retrieve_schema(state):
        if use_retrieval:
            tables = retrieve(state["question"], state["db_id"], k=k)["tables"]
        else:
            tables = all_tables(state["db_id"])
        schema_text = format_schema(state["db_id"], tables)
        entry = {"step": "retrieve_schema", "tables": tables}
        return {"schema_text": schema_text, "tables": tables,
                "history": state["history"] + [entry]}

    def generate(state):
        if state["sql"]:  # a SQL was supplied for testing; use it instead of asking the LLM
            sql = state["sql"]
        else:
            prompt = GENERATOR_PROMPT.format(
                schema=state["schema_text"], question=state["question"]
            )
            sql = clean_sql(ask_llm(prompt))
        entry = {"step": "generate", "sql": sql}
        return {"sql": sql, "history": state["history"] + [entry]}

    def execute(state):
        rows, error = run_sql(state["db_id"], state["sql"])
        entry = {"step": "execute", "ok": error is None, "error": error}
        return {"result": rows, "error": error,
                "history": state["history"] + [entry]}

    def correct(state):
        prompt = CORRECTOR_PROMPT.format(
            schema=state["schema_text"], question=state["question"],
            sql=state["sql"], error=state["error"],
        )
        new_sql = clean_sql(ask_llm(prompt))
        entry = {"step": "correct", "sql": new_sql, "attempt": state["retry_count"] + 1}
        return {"sql": new_sql, "retry_count": state["retry_count"] + 1,
                "history": state["history"] + [entry]}

    def route(state):
        if state["error"] is None:
            return "done"
        if state["retry_count"] >= max_retries:
            return "done"   # out of retries: stop instead of looping forever
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
    g.add_edge("correct", "execute")   # the loop-back edge

    return g.compile()


def run_agent(question, db_id, use_retrieval=True, max_retries=3, k=3, seed_sql=""):
    app = build_graph(use_retrieval, max_retries, k)
    return app.invoke({
        "question": question, "db_id": db_id, "schema_text": "", "tables": [],
        "sql": seed_sql, "result": None, "error": None,
        "retry_count": 0, "history": [],
    })