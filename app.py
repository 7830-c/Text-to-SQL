import datetime
import json
import threading
from pathlib import Path

import pandas as pd
import streamlit as st

import config
from agent import stream_agent
from executor import preview_sql
from schema_utils import get_db_path, get_schema
from uploads import cleanup_old_uploads, delete_upload, save_upload

st.set_page_config(page_title="Text-to-SQL Agent", page_icon="🗄️", layout="wide")
st.markdown("""
<style>
.chip{display:inline-block;padding:3px 11px;border-radius:999px;font-size:.8rem;font-weight:600;border:1px solid}
.chip.ok{background:rgba(46,158,107,.15);color:#2e9e6b;border-color:rgba(46,158,107,.4)}
.chip.bad{background:rgba(224,86,86,.15);color:#e05656;border-color:rgba(224,86,86,.4)}
.chip.fix{background:rgba(230,168,23,.15);color:#e6a817;border-color:rgba(230,168,23,.4)}
.arrow{margin:0 6px;opacity:.5}
</style>
""", unsafe_allow_html=True)

cleanup_old_uploads()
st.session_state.setdefault("asked", 0)


# ---------- helpers ----------
@st.cache_resource
def demo_counter():
    """One counter shared by every visitor (public mode only)."""
    return {"day": "", "count": 0, "lock": threading.Lock()}


def use_demo_slot():
    c = demo_counter()
    with c["lock"]:
        today = datetime.date.today().isoformat()
        if c["day"] != today:
            c["day"], c["count"] = today, 0
        if c["count"] >= config.DEMO_DAILY_LIMIT:
            return False
        c["count"] += 1
        return True


def unique(cols):
    seen, out = {}, []
    for c in cols:
        seen[c] = seen.get(c, 0) + 1
        out.append(c if seen[c] == 1 else f"{c}_{seen[c]}")
    return out


def chips(history):
    parts = []
    for h in history:
        s = h["step"]
        if s == "retrieve_schema":
            label, cls = "Retrieve schema", "ok"
        elif s == "generate":
            label, cls = "Generate SQL", "ok"
        elif s == "execute":
            label, cls = ("Execute", "ok") if h["ok"] else ("Execute: error", "bad")
        else:
            label, cls = f"Correct #{h['attempt']}", "fix"
        parts.append(f'<span class="chip {cls}">{label}</span>')
    return '<span class="arrow">→</span>'.join(parts)


@st.cache_data
def example_questions(db_id):
    p = Path(config.SPIDER_DIR) / "dev.json"
    if not p.exists():
        return []
    dev = json.load(open(p, encoding="utf-8"))
    return [x["question"] for x in dev if x["db_id"] == db_id][:3]


def show_result(r):
    st.markdown(chips(r["history"]), unsafe_allow_html=True)
    if r["error"]:
        st.error("The agent could not get a working query. Last database error:")
        st.code(r["error"])

    t_ans, t_sql, t_schema, t_trace = st.tabs(["Answer", "SQL", "Schema used", "Trace"])
    with t_ans:
        if r["df"] is not None:
            st.dataframe(r["df"])
            note = f"{len(r['df'])} rows"
            if r["more"]:
                note += f" (first {config.UI_ROW_LIMIT} shown)"
            st.caption(note)
            st.download_button("Download CSV", r["df"].to_csv(index=False), "result.csv", "text/csv")
    with t_sql:
        st.code(r["sql"], language="sql")
        st.caption("Generated SQL can be wrong. Check it against your question.")
    with t_schema:
        st.write("Tables sent to the model:", ", ".join(r["tables"]))
        st.code(r["schema_text"], language="sql")
    with t_trace:
        for h in r["history"]:
            s = h["step"]
            if s == "retrieve_schema":
                st.markdown("**Retrieve schema:** " + ", ".join(h["tables"]))
            elif s == "generate":
                st.markdown("**Generate SQL**")
                st.code(h["sql"], language="sql")
            elif s == "execute":
                st.markdown("**Execute:** " + ("ok" if h["ok"] else "error"))
                if h["error"]:
                    st.code(h["error"])
            else:
                st.markdown(f"**Correct, attempt {h['attempt']}**")
                st.code(h["sql"], language="sql")


# ---------- sidebar ----------
provider, api_key = None, None
with st.sidebar:
    st.header("Database")
    source = st.radio("Source", ["Sample database", "Upload your own"], label_visibility="collapsed")
    db_id = None

    if source == "Sample database":
        sample_dir = Path(config.SPIDER_DIR) / "database"
        samples = sorted(p.name for p in sample_dir.iterdir() if p.is_dir()) if sample_dir.exists() else []
        if samples:
            db_id = st.selectbox("Choose a database", samples)
        else:
            st.error(f"No sample databases found in {sample_dir}")
    else:
        st.caption(
            "**Sent to the AI provider:** your question, the table and column names and types, "
            "and any SQL error messages. **Not sent:** the rows in your database. "
            f"Files are deleted when you replace them, or after about {config.UPLOAD_TTL_MIN} minutes. "
            "Even so, do not upload confidential data. Names can be sensitive, and providers' "
            "terms for free API keys may allow using prompts to improve their products."
        )
        up = st.file_uploader("SQLite file", type=["sqlite", "sqlite3", "db"])
        if up is not None:
            sig = (up.name, up.size)
            uid = st.session_state.get("upload_id")
            if st.session_state.get("upload_sig") != sig or not (uid and get_db_path(uid).exists()):
                delete_upload(uid)
                uid, err = save_upload(up.getvalue())
                st.session_state["upload_id"], st.session_state["upload_sig"] = uid, sig
                if err:
                    st.error(err)
            db_id = uid
        else:
            delete_upload(st.session_state.pop("upload_id", None))
            st.session_state.pop("upload_sig", None)

    with st.expander("Settings"):
        max_retries = st.slider("Self-correction attempts", 0, 3, config.MAX_RETRIES)
        st.caption(f"Databases with up to {config.SKIP_RETRIEVAL_BELOW} tables send every table. "
                   "Larger ones use schema retrieval.")

    if config.PUBLIC_MODE:
        st.divider()
        st.subheader("Use your own API key")
        left = max(config.DEMO_QUESTIONS_PER_SESSION - st.session_state["asked"], 0)
        st.caption(f"Free demo questions left: {left}. Paste your own free key to remove the limit. "
                   "It is kept only in this session's memory, used for your requests, and never saved.")
        choice = st.selectbox("Provider", ["Gemini (Google AI Studio)", "Groq"])
        key = st.text_input("API key", type="password")
        if key.strip():
            provider = "google" if choice.startswith("Gemini") else "groq"
            api_key = key.strip()

# ---------- main page ----------
st.title("Text-to-SQL Agent")
st.caption("Ask in plain English. The agent writes SQL, runs it, and fixes its own errors.")

tab_ask, tab_bench = st.tabs(["Ask", "Benchmark"])

with tab_ask:
    if db_id and source == "Sample database":
        for i, q in enumerate(example_questions(db_id)):
            st.button(q, key=f"ex{i}", on_click=lambda q=q: st.session_state.update(q=q))

    question = st.text_input("Your question", key="q", placeholder="e.g. How many singers are there?")
    go = st.button("Run", type="primary", disabled=not (db_id and question.strip()))

    if go:
        blocked = None
        if config.PUBLIC_MODE and not api_key:
            if st.session_state["asked"] >= config.DEMO_QUESTIONS_PER_SESSION:
                blocked = ("You have used your free demo questions. Paste your own free API key "
                           "in the sidebar to continue.")
            elif not use_demo_slot():
                blocked = ("Today's shared demo allowance is used up. Paste your own free API key "
                           "in the sidebar, or try again tomorrow.")
        if blocked:
            st.warning(blocked)
        else:
            if config.PUBLIC_MODE and not api_key:
                st.session_state["asked"] += 1
            try:
                get_db_path(db_id).touch()          # keeps an upload alive while in use
                n_tables = len(get_schema(db_id))
            except Exception:
                st.error("Could not read this database.")
                st.stop()

            use_retrieval = n_tables > config.SKIP_RETRIEVAL_BELOW
            state = {"history": [], "sql": "", "error": None, "tables": [], "schema_text": ""}
            try:
                with st.status("Working on it...", expanded=True) as status:
                    for node, update in stream_agent(question.strip(), db_id, use_retrieval, max_retries,
                                                     config.RETRIEVAL_K, provider, api_key):
                        state.update(update)
                        if node == "retrieve_schema":
                            st.write(f"Schema: using {len(update['tables'])} of {n_tables} tables")
                        elif node == "generate":
                            st.write("Wrote a SQL query")
                        elif node == "execute":
                            st.write("Query ran successfully" if update["error"] is None
                                     else f"Database error: {update['error']}")
                        elif node == "correct":
                            st.write(f"Correction attempt {update['retry_count']}: rewrote the query")
                    ok = state["error"] is None
                    status.update(label="Done" if ok else "Could not get a working query",
                                  state="complete" if ok else "error", expanded=False)
            except Exception as e:
                st.error(f"The AI provider returned an error: {str(e)[:300]}")
                st.stop()

            df, more = None, False
            if state["error"] is None:
                cols, rows, more, err = preview_sql(db_id, state["sql"], config.UI_ROW_LIMIT)
                if err:
                    state["error"] = err
                else:
                    df = pd.DataFrame(rows, columns=unique(cols))

            st.session_state["result"] = {
                "db_id": db_id, "sql": state["sql"], "error": state["error"],
                "history": state["history"], "tables": state["tables"],
                "schema_text": state["schema_text"], "df": df, "more": more,
            }

    r = st.session_state.get("result")
    if r and r["db_id"] == db_id:
        show_result(r)

with tab_bench:
    img = Path(config.RESULTS_DIR) / "ablation.png"
    meta = Path(config.RESULTS_DIR) / "meta.json"
    if img.exists():
        st.image(str(img))
        if meta.exists():
            m = json.loads(meta.read_text())
            st.caption(f"Model: {m['model']}. {m['n']} random Spider dev questions. Metric: execution accuracy.")
    else:
        st.info("Run benchmark.py and analyze.py to see the ablation chart here.")