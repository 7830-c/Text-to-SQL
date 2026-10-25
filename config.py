import os
from dotenv import load_dotenv

load_dotenv()

# data and retrieval 
SPIDER_DIR = os.getenv("SPIDER_DIR", "spider_data")
MODEL_NAME = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")
RETRIEVAL_K = int(os.getenv("RETRIEVAL_K", "3"))


# benchmark
BENCH_N = int(os.getenv("BENCH_N", "150"))
BENCH_SEED = int(os.getenv("BENCH_SEED", "42"))
RESULTS_DIR = os.getenv("RESULTS_DIR", "results")

# agent
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
LLM_RETRIES = int(os.getenv("LLM_RETRIES", "3"))
LLM_BACKOFF_S = int(os.getenv("LLM_BACKOFF_S", "10"))

# LLM
LLM_CHAIN = [x.strip().lower() for x in os.getenv("LLM_CHAIN", "google,groq").split(",") if x.strip()]
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))


def model_of(provider):
    return os.getenv(f"{provider.upper()}_MODEL", "")


def rpm_of(provider):
    return float(os.getenv(f"{provider.upper()}_RPM", "10"))