import re
import time

import config

calls = {}        # successful answers per provider, e.g. {"google": 40}
_clients = {}
_last_call = {}


def _client(name):
    """Build each model only when it is first used."""
    if name not in _clients:
        model = config.model_of(name)
        if not model:
            raise ValueError(f"Set {name.upper()}_MODEL in your .env file")
        temp = config.LLM_TEMPERATURE
        if name == "google":
            from langchain_google_genai import ChatGoogleGenerativeAI
            #_clients[name] = ChatGoogleGenerativeAI(model=model, temperature=temp, max_retries=1)
            _clients[name] = ChatGoogleGenerativeAI(model=model, max_retries=1)
        elif name == "groq":
            from langchain_groq import ChatGroq
            _clients[name] = ChatGroq(model=model, temperature=temp, max_retries=1)
        else:
            raise ValueError(f"Unknown provider '{name}'. Add it here with one more elif.")
    return _clients[name]


def _text(response):
    content = response.content
    if isinstance(content, list):
        content = "".join(p if isinstance(p, str) else p.get("text", "") for p in content)
    return content
def ask_llm(prompt, provider=None):
    """Try each provider in LLM_CHAIN in order. provider='groq' forces just that one."""
    chain = [provider] if provider else config.LLM_CHAIN
    last_err = None
    for name in chain:
        for attempt in range(config.LLM_RETRIES):
            try:
                wait = _last_call.get(name, 0) + 60 / config.rpm_of(name) - time.time()
                if wait > 0:
                    time.sleep(wait)          # stay under this provider's requests per minute
                _last_call[name] = time.time()

                out = _text(_client(name).invoke(prompt))
                calls[name] = calls.get(name, 0) + 1
                return out
            except Exception as e:
                last_err = e
                print(f"[{name}] attempt {attempt + 1} failed: {str(e)[:100]}")
                if not _temporary(e):
                    break                      # wrong key, bad model id...: retrying won't help
                time.sleep(config.LLM_BACKOFF_S * (attempt + 1))   # wait 10s, 20s, 30s
    raise last_err

def clean_sql(text):
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if m:
        text = m.group(1)
    text = text.strip()
    if ";" in text:
        text = text.split(";")[0]
    return text.strip()


def _temporary(e):
    """Errors worth waiting for: server overloaded, timeouts, per-minute rate limits."""
    t = str(e).lower()
    return any(s in t for s in ("503", "502", "504", "500", "unavailable", "overloaded",
                                "high demand", "timeout", "deadline", "429"))