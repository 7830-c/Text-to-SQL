import os
from dotenv import load_dotenv

load_dotenv()

# On Streamlit Cloud, values from the app's Secrets settings are copied into the environment too
try:
    import streamlit as st
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ.setdefault(_k, _v)
except Exception:
    pass

# data and retrieval
SPIDER_DIR = os.getenv("SPIDER_DIR", "spider_data")
MODEL_NAME = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")
RETRIEVAL_K = int(os.getenv("RETRIEVAL_K", "3"))
SKIP_RETRIEVAL_BELOW = int(os.getenv("SKIP_RETRIEVAL_BELOW", "6"))  # databases this small send all tables

# agent
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

# LLM
LLM_CHAIN = [x.strip().lower() for x in os.getenv("LLM_CHAIN", "google,groq").split(",") if x.strip()]
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))
LLM_RETRIES = int(os.getenv("LLM_RETRIES", "3"))
LLM_BACKOFF_S = int(os.getenv("LLM_BACKOFF_S", "10"))


def model_of(provider):
    return os.getenv(f"{provider.upper()}_MODEL", "")


def rpm_of(provider):
    return float(os.getenv(f"{provider.upper()}_RPM", "10"))


# benchmark
BENCH_N = int(os.getenv("BENCH_N", "150"))
BENCH_SEED = int(os.getenv("BENCH_SEED", "42"))
RESULTS_DIR = os.getenv("RESULTS_DIR", "results")

# app
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "35"))
UPLOAD_TTL_MIN = int(os.getenv("UPLOAD_TTL_MIN", "60"))   # uploads older than this are deleted
UI_ROW_LIMIT = int(os.getenv("UI_ROW_LIMIT", "200"))

# public deployment (leave PUBLIC_MODE off locally)
PUBLIC_MODE = os.getenv("PUBLIC_MODE", "0") == "1"
DEMO_QUESTIONS_PER_SESSION = int(os.getenv("DEMO_QUESTIONS_PER_SESSION", "5"))
DEMO_DAILY_LIMIT = int(os.getenv("DEMO_DAILY_LIMIT", "200"))   # questions per day, all visitors combined

PICKER_MIN_TABLES = int(os.getenv("PICKER_MIN_TABLES", "30"))   # databases bigger than this use the LLM table picker