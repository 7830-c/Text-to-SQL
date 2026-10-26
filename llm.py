import re
import threading
import time
import warnings

import config

warnings.filterwarnings("ignore", message=".*fixed sampling defaults.*")

calls = {}          # successful answers per provider
_clients = {}
_last_call = {}
_lock = threading.Lock()


def _build(name, api_key=None):
    model = config.model_of(name)
    if not model:
        raise ValueError(f"Set {name.upper()}_MODEL in your .env file")
    temp = config.LLM_TEMPERATURE
    if name == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        extra = {"google_api_key": api_key} if api_key else {}
        return ChatGoogleGenerativeAI(model=model, temperature=temp, max_retries=1, **extra)
    if name == "groq":
        from langchain_groq import ChatGroq
        extra = {"api_key": api_key} if api_key else {}
        return ChatGroq(model=model, temperature=temp, max_retries=1, **extra)
    raise ValueError(f"Unknown provider '{name}'. Add it here with one more branch.")


def _client(name, api_key=None):
    if api_key:                      # a visitor's own key: built per call, never cached or shared
        return _build(name, api_key)
    if name not in _clients:
        _clients[name] = _build(name)
    return _clients[name]


def _throttle(name):
    """Keep the shared key under its requests-per-minute limit, even with several visitors."""
    with _lock:
        wait = _last_call.get(name, 0) + 60 / config.rpm_of(name) - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_call[name] = time.time()


def _text(response):
    content = response.content
    if isinstance(content, list):
        content = "".join(p if isinstance(p, str) else p.get("text", "") for p in content)
    return content


def _temporary(e):
    t = str(e).lower()
    return any(s in t for s in ("503", "502", "504", "500", "unavailable", "overloaded",
                                "high demand", "timeout", "deadline", "429"))


def ask_llm(prompt, provider=None, api_key=None, info=None):
    """Try each provider in LLM_CHAIN in order. With provider=..., use only that one.
    With api_key=..., use the visitor's own key (and only that provider).
    If an `info` dict is passed, it is filled with which model answered and how long it took."""
    chain = [provider] if provider else config.LLM_CHAIN
    last_err = None
    for name in chain:
        for attempt in range(config.LLM_RETRIES):
            try:
                if not api_key:
                    _throttle(name)
                t0 = time.time()
                out = _text(_client(name, api_key).invoke(prompt))
                calls[name] = calls.get(name, 0) + 1
                if info is not None:
                    info.update(provider=name, model=config.model_of(name),
                                seconds=round(time.time() - t0, 2), attempts=attempt + 1)
                return out
            except Exception as e:
                last_err = e
                print(f"[{name}] attempt {attempt + 1} failed: {str(e)[:100]}")
                if not _temporary(e):
                    break
                time.sleep(config.LLM_BACKOFF_S * (attempt + 1))
    raise last_err


def clean_sql(text):
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if m:
        text = m.group(1)
    text = text.strip()
    if ";" in text:
        text = text.split(";")[0]
    return text.strip()