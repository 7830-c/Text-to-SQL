# 🗄️ Agentic Text-to-SQL System

An enterprise-grade, self-correcting Text-to-SQL engine built with **LangGraph**, **SQLite**, **SentenceTransformers (FAISS)**, and **Multi-Provider LLMs** (Google Gemini & Groq/LLaMA). It translates natural language questions into accurate, executable SQLite queries, executes them securely, and features an automated multi-stage self-healing and data-grounding pipeline.

---

## 📌 Table of Contents

- [Overview](#overview)
- [Key Capabilities & Features](#key-capabilities--features)
- [Architecture & Workflow](#architecture--workflow)
- [Project Structure](#project-structure)
- [Installation & Setup](#installation--setup)
- [Configuration (.env)](#configuration-env)
- [How to Use](#how-to-use)
  - [1. Running the Streamlit Web Application](#1-running-the-streamlit-web-application)
  - [2. CLI & Programmatic Agent Execution](#2-cli--programmatic-agent-execution)
  - [3. Running Benchmarks & Spider Evaluation](#3-running-benchmarks--spider-evaluation)
  - [4. Diagnostic & Inspection Utilities](#4-diagnostic--inspection-utilities)
- [Error Handling & Self-Correction Mechanisms](#error-handling--self-correction-mechanisms)
- [Security & Safety Safeguards](#security--safety-safeguards)
- [License & Acknowledgments](#license--acknowledgments)

---

## 📖 Overview

Standard Text-to-SQL pipelines often fail in real-world scenarios due to:
1. **Schema Overload:** Databases with dozens or hundreds of tables overwhelm LLM context windows.
2. **Schema Hallucination:** LLMs invent column names or mistake foreign key relations.
3. **Value Mismatches:** Queries fail because text comparisons don't match the exact casing, spacing, or format of the stored records.
4. **Silent Empty Results:** Queries execute without syntax errors, but return 0 rows due to overly strict or misaligned filters.

This project solves these challenges by combining:
- **Intelligent Schema Retrieval & Pruning** (FAISS semantic search + Foreign Key inference + LLM catalog picking).
- **Automated Schema Documentation & Data Dictionaries** (summarizing tables and domain terminology before querying).
- **Active Data Grounding** (inspecting real database enum values and matching keywords from the question).
- **Multi-Layered Self-Healing Execution** (AST-based text relaxation + database error feedback loops + soft error diagnostics).

---

## 🚀 Key Capabilities & Features

### 1. Adaptive Schema Retrieval & Selection
- **Small Databases ($\le 6$ tables):** All tables are provided directly to the model.
- **Medium Databases:** Dense vector embeddings using `SentenceTransformer (all-MiniLM-L6-v2)` and `FAISS` retrieve top-$k$ relevant tables based on table names, column definitions, and value samples.
- **Foreign Key Graph Expansion:** Automatically pulls joined tables along primary/foreign key relationships. Includes **inferred join detection** for schema designs lacking explicit foreign keys (e.g., `user_id` $\rightarrow$ `accounts_user.id`).
- **Large Databases ($> 30$ tables):** Employs an LLM Table Picker (`pick_tables_llm`) that reviews a compact catalog and prunes empty tables before query generation.

### 2. Auto-Generated Data Dictionaries (`dictionary.py`)
- Automatically batches and analyzes tables to write 1-line table descriptions, domain overviews, and structural notes.
- Caches generated dictionaries by hashing schema structure (`dict_cache/`), eliminating redundant LLM calls.
- Injects enriched table descriptions directly into both the embedding documents and the query generation prompts.

### 3. Active Data Grounding (`grounding.py`)
- Searches string columns for exact or substring matches of words from the user's question before generating SQL.
- Extracts and presents low-cardinality enum values ($\le 12$ distinct options) to prevent the model from guessing status codes, categories, or classifications.
- Strictly ignores sensitive columns (passwords, tokens, emails, hashes, personal contact fields).

### 4. 3-Tier Self-Correction & Recovery (`recovery.py`)
- **Tier 1 (Database Error Feedback Loop):** Catches SQLite syntax errors, missing columns, or bad table references and passes the error trace directly to `CORRECTOR_PROMPT` to rewrite the query.
- **Tier 2 (Zero-Cost AST Query Relaxation):** If a query executes successfully but yields 0 rows, `sqlglot` transforms exact equality checks into case-insensitive, whitespace-trimmed filters (`LOWER(TRIM(col)) = LOWER('val')`) and re-executes without calling the LLM.
- **Tier 3 (Soft Error Diagnostics & Evidence Generation):** If relaxed queries still yield 0 rows, the system scans the database for actual values matching question tokens and feeds evidence back to the model for targeted refinement.

### 5. Multi-Provider Fallback & Rate Limiting (`llm.py`)
- Primary and secondary LLM routing (e.g., `google` Gemini with fallback to `groq` LLaMA 3.3).
- Thread-safe Requests-Per-Minute (`RPM`) throttling.
- Exponential backoff on transient network and server errors (`429`, `503`, timeouts).
- Support for user-provided API keys in shared/public deployment settings.

### 6. Interactive Streamlit UI (`app.py`)
- Support for built-in Spider sample databases and user-uploaded SQLite files (`.sqlite`, `.sqlite3`, `.db`).
- Visual step-by-step execution timeline ("chips" indicating schema selection, grounding, generation, execution, and correction iterations).
- Real-time tabular data display, row pagination, and one-click CSV download.
- Full inspection tabs for the generated SQL query, executed schema, and raw model prompts.
- Built-in database overview generation panel with progress tracking.

---

## 🏗️ Architecture & Workflow

The agent execution flow is orchestrated via **LangGraph**:

```
                       ┌───────────────────────┐
                       │   Natural Language    │
                       │     User Question     │
                       └──────────┬────────────┘
                                  │
                                  ▼
                       ┌───────────────────────┐
                       │  retrieve_schema      │
                       │ (FAISS / Picker / FK) │
                       └──────────┬────────────┘
                                  │
                  ┌───────────────┴───────────────┐
       (Look at Data enabled)            (Default path)
                  │                               │
                  ▼                               │
       ┌───────────────────────┐                  │
       │     ground data       │                  │
       │ (Enums & value lookup)│                  │
       └──────────┬────────────┘                  │
                  │                               │
                  └───────────────┬───────────────┘
                                  │
                                  ▼
                       ┌───────────────────────┐
                       │     generate SQL      │
                       │ (LLM Generator Prompt)│
                       └──────────┬────────────┘
                                  │
                                  ▼
                       ┌───────────────────────┐
                       │      execute SQL      │
                       │ (Read-Only / sqlglot) │
                       └──────────┬────────────┘
                                  │
                  ┌───────────────┴───────────────┐
             [Execution Error]              [Successful Execution]
                  │                               │
                  ▼                               ▼
       ┌───────────────────────┐         ┌─────────────────┐
       │   Retry Count < Max?  │         │  Returns Rows?  │
       └───┬───────────────┬───┘         └────────┬────────┘
          Yes              No                     │
           │               │            Yes ◄─────┴─────► No (0 Rows)
           │               │             │                     │
           ▼               ▼             ▼                     ▼
     ┌───────────┐     ┌───────┐    ┌─────────┐      ┌──────────────────┐
     │  correct  │     │  END  │    │   END   │      │ Layer 2: Relax   │
     │   (LLM)   │     │(Fail) │    │(Success)│      │ AST (sqlglot)    │
     └─────┬─────┘     └───────┘    └─────────┘      └────────┬─────────┘
           │                                                  │
           └──────────────────────────────────────────────────┴────────┐
                                                                       │
                                                       If still 0 rows │
                                                                       ▼
                                                             ┌──────────────────┐
                                                             │ Layer 3: Soft    │
                                                             │ Error Evidence   │
                                                             └────────┬─────────┘
                                                                      │
                                                                      ▼
                                                             ┌──────────────────┐
                                                             │  Route to retry  │
                                                             └──────────────────┘
```

---

## 📁 Project Structure

```
.
├── app.py                  # Streamlit web application interface
├── agent.py                # LangGraph StateGraph agent definition & streaming
├── retriever.py            # SentenceTransformer embeddings, FAISS index, FK expansion
├── grounding.py            # Active data grounding (enum extraction, value search)
├── recovery.py             # Query relaxation (sqlglot AST) and soft-recovery evidence
├── dictionary.py           # Database overview & table documentation generator/cacher
├── executor.py             # Secure read-only SQLite execution & AST safety checks
├── schema_utils.py         # SQLite schema extraction, sample loading, FK inference
├── prompts.py              # System prompts for generation, correction, picker, dictionary
├── llm.py                  # Multi-provider LLM client (Gemini, Groq) with throttling
├── config.py               # Central configuration loaded from .env / Streamlit secrets
├── uploads.py              # File upload validation, storage, and TTL auto-cleanup
├── benchmark.py            # Spider evaluation runner (baseline vs full agent)
├── analyze.py              # Evaluation analysis, accuracy metrics & ablation chart
├── compare.py              # Set- & order-aware SQL result evaluation helper
├── eval_retrieval.py       # Standalone recall evaluation for the retriever
├── inspect_db.py           # CLI tool to inspect any SQLite database structure
├── check_wrong.py          # CLI diagnostic tool to inspect failed benchmark queries
├── check_values.py         # CLI utility to find value occurrences across tables
├── debug_retrieval.py      # Quick CLI to test FAISS similarity rankings
├── test_agent.py           # Quick integration and sanity tests for agent workflows
├── dict_cache/             # Cached database dictionary JSON files
├── spider_data/            # Spider benchmark databases and dev.json dataset
├── results/                # Benchmark JSONL logs, ablation charts, and analysis output
└── uploads/                # Temporary directory for user-uploaded SQLite databases
```

---

## ⚙️ Installation & Setup

### Prerequisites
- Python 3.10+
- SQLite3
- Recommended: A virtual environment (`venv` or `conda`)

### Step 1: Clone the Repository & Create Virtual Environment
```bash
git clone <repository-url>
cd Text-to-SQL

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
```

### Step 2: Install Dependencies
```bash
pip install -r requirements.txt
```
*(If `requirements.txt` is not present, install core dependencies directly)*:
```bash
pip install streamlit langgraph langchain-google-genai langchain-groq sentence-transformers faiss-cpu sqlglot python-dotenv pandas matplotlib
```

---

## 🔑 Configuration (.env)

Create a `.env` file in the root directory (refer to the settings below):

```ini
# --- API Keys ---
GOOGLE_API_KEY="your-google-ai-studio-api-key"
GROQ_API_KEY="your-groq-api-key"

# --- Model Selection & Provider Fallback ---
# Comma-separated list in order of priority: e.g. "google,groq" or "google"
LLM_CHAIN=google
LLM_TEMPERATURE=0
LLM_RETRIES=3
LLM_BACKOFF_S=10

# Google Gemini Settings
GOOGLE_MODEL=gemini-2.5-flash
GOOGLE_RPM=12

# Groq Settings
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_RPM=10

# --- Retrieval & Vector Search ---
EMBED_MODEL=all-MiniLM-L6-v2
RETRIEVAL_K=3
SKIP_RETRIEVAL_BELOW=6
PICKER_MIN_TABLES=30

# --- Agent Self-Correction ---
MAX_RETRIES=3
SOFT_RETRIES=2

# --- Web Application & Uploads ---
SPIDER_DIR=spider_data
UPLOAD_DIR=uploads
DICT_DIR=dict_cache
MAX_UPLOAD_MB=35
UPLOAD_TTL_MIN=60
UI_ROW_LIMIT=200

# Set to 1 when hosting publicly to enable visitor rate limits
PUBLIC_MODE=0
DEMO_QUESTIONS_PER_SESSION=5
DEMO_DAILY_LIMIT=200
```

---

## 💻 How to Use

### 1. Running the Streamlit Web Application

Launch the interactive UI:
```bash
streamlit run app.py
```
Open your browser at `http://localhost:8501`.

#### Web UI Highlights:
- **Choose Database:** Select any pre-loaded Spider database from the dropdown, or upload any `.sqlite` database up to 35 MB.
- **Build Overview:** Click **"Build overview"** to generate domain descriptions for all tables.
- **Ask Questions:** Type your question in natural language (e.g., *"Which singer released the most albums in 2020?"*).
- **Inspect Trajectory:** Expand **"How the agent got this answer"** to see table retrieval scores, generated SQL, error feedback loops, and LLM latency.
- **Export Results:** View query results in a clean table and download them as CSV.

---

### 2. CLI & Programmatic Agent Execution

You can run the agent directly in Python scripts:

```python
from agent import run_agent

# Run agent on a database with retrieval and self-correction
state = run_agent(
    question="What is the average age of singers from France?",
    db_id="concert_singer",
    use_retrieval=True,
    max_retries=3,
    k=3
)

print("Generated SQL :", state["sql"])
print("Query Result  :", state["result"])
print("Total Retries :", state["retry_count"])
```

Run quick built-in test suites:
```bash
python test_agent.py
```

---

### 3. Running Benchmarks & Spider Evaluation

The project includes an end-to-end evaluation suite on the **Spider** cross-domain Text-to-SQL benchmark.

#### Run Baseline vs. Full Agent:
```bash
# 1. Run baseline (all tables sent, 0 correction retries)
python benchmark.py baseline

# 2. Run full system (FAISS retrieval + self-correction enabled)
python benchmark.py full
```
*Note: Benchmarking supports resumption; rerunning the command automatically continues from where it stopped.*

#### Compute Accuracy & Generate Ablation Chart:
```bash
python analyze.py
```
Outputs:
- Execution accuracy for **Baseline vs. +Retrieval vs. +Self-Correction** with 95% confidence intervals.
- Breakdown of error categories (syntax errors, missing tables/columns, ambiguous joins).
- Saves the visual ablation chart to `results/ablation.png`.

---

### 4. Diagnostic & Inspection Utilities

The project includes several specialized CLI tools for database administration and prompt tuning:

- **Inspect SQLite Schema:**
  ```bash
  python inspect_db.py spider_data/database/concert_singer/concert_singer.sqlite [optional_keyword]
  ```
- **Evaluate Retrieval Recall:**
  ```bash
  python eval_retrieval.py
  ```
- **Test Value Occurrences:**
  ```bash
  python check_values.py spider_data/database/concert_singer/concert_singer.sqlite "John" "Paris"
  ```
- **Debug FAISS Retrieval Ranking:**
  ```bash
  python debug_retrieval.py concert_singer "Find stadiums with capacity above 50000"
  ```
- **Review Failed Benchmark Queries:**
  ```bash
  python check_wrong.py results
  ```

---

## 🛡️ Error Handling & Self-Correction Mechanisms

| Failure Mode | Trigger / Condition | Resolution Strategy |
| :--- | :--- | :--- |
| **Syntax / Column Error** | SQLite raises `sqlite3.OperationalError` | `correct` node feeds error details directly back into the LLM with the previous SQL to formulate a fix. |
| **Strict Casing Mismatch** | Query runs fine, returns 0 rows | **AST Relaxation:** Automatically rewrites conditions using `LOWER(TRIM(col))` without consuming LLM tokens. |
| **Silent 0-Row Output** | Relaxed query still returns 0 rows | **Soft Error Evidence:** Scans database for close string matches and supplies actual data samples in the correction prompt. |
| **Missing Foreign Keys** | Incomplete join paths in raw schema | **FK Inference:** Detects naming patterns (`<table_stem>_id`) to add join paths to the schema context. |
| **API Rate Limits / 429** | LLM provider quotas hit | Thread-safe RPM throttling + automatic exponential backoff retry loop. |
| **Provider Outage** | 5xx errors from primary provider | Automatic failover to secondary provider defined in `LLM_CHAIN`. |

---

## 🔒 Security & Safety Safeguards

1. **Read-Only SQLite Engine:** All database connections are opened using URI parameters with `mode=ro` (`read-only`).
2. **SQL AST Validation (`sqlglot`):**
   - Strictly permits `SELECT` statements (and union set operations).
   - Actively blocks all data mutation and schema alteration statements (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, `ALTER`).
3. **Execution Timeout Guards:** SQLite connection progress handlers enforce a strict 30-second timeout to prevent DoS via runaway recursive queries or accidental Cartesian products.
4. **Data Privacy Guardrails:**
   - Database rows are **never** dumped indiscriminately into LLM prompts.
   - PII and credential columns (`password`, `token`, `email`, `otp`, `secret`, `address`) are explicitly blacklisted from active grounding searches.
5. **Upload Lifespan Management:** Uploaded SQLite files are hashed, sanitized, and automatically purged after their configured Time-To-Live (`UPLOAD_TTL_MIN`).

---

## 📄 License & Acknowledgments

- Built using the [Spider Text-to-SQL Benchmark](https://yale-lily.github.io/spider) dataset.
- Compatible with models via [Google AI Studio](https://ai.google.dev/) and [Groq Cloud](https://groq.com/).
