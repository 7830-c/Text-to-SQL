import datetime
import json
import os
import random
import sqlite3
import threading
import time
from pathlib import Path
import math

import dictionary
import pandas as pd
import streamlit as st

import config
from agent import stream_agent
from executor import preview_sql
from schema_utils import get_db_path, get_schema
from uploads import cleanup_old_uploads, delete_upload, save_upload

# ── page config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="QueryForge", page_icon=None, layout="wide")

# ── known providers ───────────────────────────────────────────────────────────
_ALL_PROVIDERS = ["google", "groq"]


def _available_providers():
    return [p for p in _ALL_PROVIDERS if config.model_of(p)]


def _provider_label(p: str) -> str:
    model = config.model_of(p)
    if p == "google":
        name = model.replace("gemini-", "Gemini ").replace("-", " ").title() if model else "Gemini"
        return f"{name} (Google)"
    if p == "groq":
        return f"{model} (Groq)" if model else "Groq"
    return p.title()


# ── session state defaults ────────────────────────────────────────────────────
st.session_state.setdefault("dark_mode", False)
st.session_state.setdefault("asked", 0)
st.session_state.setdefault("show_prompts", False)
st.session_state.setdefault("look_at_data", not config.PUBLIC_MODE)
st.session_state.setdefault("max_retries", config.MAX_RETRIES)
st.session_state.setdefault("pinned_provider", None)
st.session_state.setdefault("custom_key_provider",
    _available_providers()[0] if _available_providers() else "google")
st.session_state.setdefault("custom_api_key", "")

dark = st.session_state["dark_mode"]


# ── CSS ───────────────────────────────────────────────────────────────────────
def inject_css(is_dark: bool):
    if is_dark:
        # VS Code Dark+ palette
        v = """
        --bg:            #1e1e1e;
        --bg2:           #252526;
        --surface:       #2d2d30;
        --surface2:      #3e3e42;
        --border:        #474747;
        --accent:        #569cd6;
        --accent2:       #9d8cff;
        --accent-subtle: rgba(86,156,214,0.12);
        --text:          #d4d4d4;
        --text2:         #858585;
        --success:       #4ec9b0;
        --warning:       #dcdcaa;
        --error:         #f44747;
        --input-bg:      #3c3c3c;
        --card-bg:       #252526;
        --shadow:        rgba(0,0,0,0.5);
        --btn-text:      #ffffff;
        """
    else:
        v = """
        --bg:            #f5f6fa;
        --bg2:           #ffffff;
        --surface:       #eef0f8;
        --surface2:      #e2e6f3;
        --border:        #d2d8ec;
        --accent:        #4f46e5;
        --accent2:       #7c3aed;
        --accent-subtle: rgba(79,70,229,0.08);
        --text:          #1a1c2e;
        --text2:         #5a6280;
        --success:       #16a34a;
        --warning:       #ca8a04;
        --error:         #dc2626;
        --input-bg:      #ffffff;
        --card-bg:       #ffffff;
        --shadow:        rgba(79,70,229,0.08);
        --btn-text:      #ffffff;
        """

    st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

:root {{ {v} }}

/* ── Hide all Streamlit chrome ── */
#MainMenu,
.stDeployButton,
[data-testid="stToolbar"],
header[data-testid="stHeader"],
footer,
section[data-testid="stSidebar"],
[data-testid="collapsedControl"] {{
    display: none !important;
}}

/* ── Global ── */
html, body, [class*="css"] {{
    font-family: 'Inter', system-ui, -apple-system, sans-serif !important;
}}
.stApp {{
    background: var(--bg) !important;
    color: var(--text) !important;
    transition: background 0.22s ease, color 0.22s ease;
}}
.block-container {{
    padding-top: 1.5rem !important;
    padding-bottom: 3rem !important;
    max-width: 1120px;
}}

/* Force text colour in dark mode */
p, li, span, label, div, td, th, small,
.stMarkdown, .stMarkdown p, .stMarkdown li,
.stText, .stCaption, [class*="st-"],
[data-testid] {{
    color: var(--text);
}}
h1, h2, h3, h4, h5 {{ color: var(--text) !important; }}
.stCaption, .stCaption p, small {{
    color: var(--text2) !important;
    font-size: 0.78rem;
}}

/* ── Buttons ── */
.stButton > button {{
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.85rem !important;
    padding: 0.4rem 1rem !important;
    border: 1px solid var(--border) !important;
    background: var(--surface) !important;
    color: var(--text) !important;
    transition: all 0.15s ease !important;
}}
.stButton > button:hover:not([disabled]) {{
    border-color: var(--accent) !important;
    color: var(--accent) !important;
    background: rgba(79,70,229,0.08) !important;
}}
/* Primary button — always white text */
.stButton > button[kind="primary"],
button[kind="primary"] {{
    background: linear-gradient(135deg, var(--accent), var(--accent2)) !important;
    color: #ffffff !important;
    border: none !important;
    padding: 0.5rem 2rem !important;
    font-size: 0.9rem !important;
    letter-spacing: 0.01em !important;
    box-shadow: 0 2px 14px rgba(79,70,229,0.3) !important;
}}
.stButton > button[kind="primary"]:hover:not([disabled]) {{
    transform: translateY(-1px) !important;
    box-shadow: 0 5px 22px rgba(79,70,229,0.45) !important;
    color: #ffffff !important;
}}
.stButton > button[kind="primary"]:disabled {{
    opacity: 0.38 !important;
    transform: none !important;
    box-shadow: none !important;
    cursor: not-allowed !important;
}}

/* ── Form submit button — white text always ── */
.stFormSubmitButton > button {{
    border-radius: 8px !important;
    font-weight: 700 !important;
    font-size: 0.9rem !important;
    padding: 0.5rem 2rem !important;
    background: linear-gradient(135deg, var(--accent), var(--accent2)) !important;
    color: #ffffff !important;
    border: none !important;
    box-shadow: 0 2px 14px rgba(79,70,229,0.3) !important;
    transition: all 0.15s ease !important;
    letter-spacing: 0.01em !important;
    font-family: 'Inter', sans-serif !important;
}}
.stFormSubmitButton > button:hover:not([disabled]) {{
    transform: translateY(-1px) !important;
    box-shadow: 0 5px 22px rgba(79,70,229,0.45) !important;
    color: #ffffff !important;
}}
.stFormSubmitButton > button:disabled {{
    opacity: 0.35 !important;
    transform: none !important;
    box-shadow: none !important;
}}

/* ── Text input — full width ── */
div[data-testid="stTextInput"] {{
    width: 100% !important;
}}
.stTextInput > div {{
    width: 100% !important;
}}
.stTextInput > div > div {{
    width: 100% !important;
}}
.stTextInput > div > div > input {{
    width: 100% !important;
    border-radius: 10px !important;
    border: 1.5px solid var(--border) !important;
    background: var(--input-bg) !important;
    color: var(--text) !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 1rem !important;
    padding: 0.7rem 1.1rem !important;
    transition: border-color 0.18s, box-shadow 0.18s !important;
    box-sizing: border-box !important;
}}
.stTextInput > div > div > input:focus {{
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px rgba(79,70,229,0.14) !important;
    outline: none !important;
}}
.stTextInput > div > div > input::placeholder {{
    color: var(--text2) !important;
    opacity: 0.8 !important;
}}
.stTextInput label {{
    color: var(--text) !important;
    font-weight: 600 !important;
    font-size: 0.88rem !important;
}}

/* ── Selectbox ── */
.stSelectbox label {{
    color: var(--text) !important;
    font-size: 0.85rem !important;
    font-weight: 500 !important;
}}
.stSelectbox > div > div {{
    background: var(--input-bg) !important;
    border: 1.5px solid var(--border) !important;
    border-radius: 8px !important;
    color: var(--text) !important;
}}
.stSelectbox [data-baseweb="select"] > div {{
    background: var(--input-bg) !important;
    color: var(--text) !important;
    border-color: var(--border) !important;
}}
.stSelectbox [data-baseweb="select"] span {{
    color: var(--text) !important;
}}
.stSelectbox svg {{ fill: var(--text2) !important; }}

/* ── Dropdown list items & popovers (Selectbox) ── */
div[data-baseweb="popover"],
div[data-baseweb="popover"] > div,
div[data-baseweb="popover"] [data-baseweb="menu"],
div[data-baseweb="popover"] ul,
div[data-baseweb="popover"] ul[role="listbox"],
[data-baseweb="menu"],
ul[role="listbox"],
[data-testid="stSelectboxVirtualDropdown"] {{
    background: var(--bg2) !important;
    background-color: var(--bg2) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    box-shadow: 0 8px 32px var(--shadow) !important;
}}

div[data-baseweb="popover"] li,
div[data-baseweb="popover"] li[role="option"],
div[data-baseweb="popover"] [role="option"],
[data-baseweb="menu"] li,
ul[role="listbox"] li,
li[role="option"] {{
    background: var(--bg2) !important;
    background-color: var(--bg2) !important;
    color: var(--text) !important;
    transition: background 0.12s ease !important;
}}

div[data-baseweb="popover"] li:hover,
div[data-baseweb="popover"] li[aria-selected="true"],
div[data-baseweb="popover"] [role="option"]:hover,
div[data-baseweb="popover"] [role="option"][aria-selected="true"],
[data-baseweb="menu"] li:hover,
[data-baseweb="menu"] li[aria-selected="true"],
ul[role="listbox"] li:hover,
ul[role="listbox"] li[aria-selected="true"],
li[role="option"]:hover,
li[role="option"][aria-selected="true"],
li[role="option"]:focus {{
    background: var(--surface2) !important;
    background-color: var(--surface2) !important;
    color: var(--accent) !important;
}}

div[data-baseweb="popover"] li *,
div[data-baseweb="popover"] [role="option"] *,
[data-baseweb="menu"] li *,
ul[role="listbox"] li *,
li[role="option"] * {{
    color: inherit !important;
    background: transparent !important;
}}

div[data-baseweb="popover"] ul::-webkit-scrollbar,
ul[role="listbox"]::-webkit-scrollbar {{
    width: 6px;
}}
div[data-baseweb="popover"] ul::-webkit-scrollbar-track,
ul[role="listbox"]::-webkit-scrollbar-track {{
    background: var(--bg2);
}}
div[data-baseweb="popover"] ul::-webkit-scrollbar-thumb,
ul[role="listbox"]::-webkit-scrollbar-thumb {{
    background: var(--surface2);
    border-radius: 4px;
}}

/* ── Radio ── */
.stRadio label, .stRadio div[role="radiogroup"] label {{
    font-size: 0.875rem !important;
    color: var(--text) !important;
}}

/* ── Toggle ── */
.stToggle label {{
    font-size: 0.85rem !important;
    color: var(--text) !important;
}}

/* ── Slider ── */
.stSlider label {{ color: var(--text) !important; font-size: 0.85rem !important; font-weight: 500 !important; }}
.stSlider [data-baseweb="slider"] [data-testid="stTickBar"] span {{ color: var(--text2) !important; }}

/* ── File uploader ── */
[data-testid="stFileUploader"] {{
    background: var(--surface) !important;
    border: 1.5px dashed var(--border) !important;
    border-radius: 10px !important;
    padding: 0.5rem !important;
}}
[data-testid="stFileUploader"] > section,
[data-testid="stFileUploader"] section,
[data-testid="stFileUploadDropzone"],
[data-testid="stFileUploaderDropzone"],
div[data-testid="stFileUploadDropzone"] {{
    background: var(--card-bg) !important;
    background-color: var(--card-bg) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    padding: 0.75rem 1rem !important;
}}
[data-testid="stFileUploader"] * {{
    color: var(--text) !important;
}}
[data-testid="stFileUploader"] button {{
    background: var(--surface2) !important;
    background-color: var(--surface2) !important;
    border: 1px solid var(--border) !important;
    color: var(--text) !important;
    border-radius: 6px !important;
}}
[data-testid="stFileUploader"] button * {{
    color: var(--text) !important;
}}
[data-testid="stFileUploader"] button:hover {{
    background: var(--accent) !important;
    background-color: var(--accent) !important;
    color: #ffffff !important;
    border-color: var(--accent) !important;
}}
[data-testid="stFileUploader"] button:hover * {{
    color: #ffffff !important;
}}
[data-testid="stFileUploader"] small,
[data-testid="stFileUploadDropzone"] small,
[data-testid="stFileUploader"] span,
[data-testid="stFileUploadDropzone"] span {{
    color: var(--text2) !important;
}}
[data-testid="stFileUploader"] svg {{
    fill: var(--text2) !important;
}}
[data-testid="stFileUploaderFile"],
[data-testid="stUploadedFile"],
[data-testid="stFileUploaderFileData"] {{
    background: var(--card-bg) !important;
    border: 1px solid var(--border) !important;
    border-radius: 6px !important;
    color: var(--text) !important;
}}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {{
    gap: 2px !important;
    border-bottom: 2px solid var(--border) !important;
    background: transparent !important;
}}
.stTabs [data-baseweb="tab"] {{
    border-radius: 6px 6px 0 0 !important;
    font-weight: 500 !important;
    font-size: 0.875rem !important;
    color: var(--text2) !important;
    padding: 0.45rem 1.1rem !important;
    background: transparent !important;
    transition: color 0.15s !important;
}}
.stTabs [aria-selected="true"] {{
    color: var(--accent) !important;
    border-bottom: 2px solid var(--accent) !important;
}}
[data-baseweb="tab-panel"] {{
    background: transparent !important;
    padding-top: 1rem !important;
}}

/* ── Expander ── */
[data-testid="stExpander"] {{
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    overflow: hidden !important;
    background: var(--card-bg) !important;
    margin-bottom: 0.85rem !important;
}}
[data-testid="stExpander"] summary {{
    background: var(--surface) !important;
    padding: 0.65rem 1rem !important;
    color: var(--text) !important;
    font-weight: 500 !important;
    font-size: 0.875rem !important;
}}
[data-testid="stExpander"] summary:hover {{
    background: var(--surface2) !important;
}}
[data-testid="stExpander"] summary p,
[data-testid="stExpander"] summary span {{
    color: var(--text) !important;
}}
[data-testid="stExpander"] summary svg {{ fill: var(--text2) !important; }}
[data-testid="stExpander"] > div > div {{
    background: var(--card-bg) !important;
    padding: 0.8rem 1rem !important;
}}

/* ── Popover ── */
[data-testid="stPopover"] button {{
    border-radius: 8px !important;
    font-weight: 600 !important;
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    color: var(--text) !important;
    font-size: 0.85rem !important;
    padding: 0.4rem 1rem !important;
    transition: all 0.15s !important;
    font-family: 'Inter', sans-serif !important;
}}
[data-testid="stPopover"] button:hover {{
    border-color: var(--accent) !important;
    color: var(--accent) !important;
}}
[data-testid="stPopoverBody"] {{
    background: var(--bg2) !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
    padding: 1.2rem !important;
    min-width: 320px !important;
    box-shadow: 0 8px 32px var(--shadow) !important;
}}
[data-testid="stPopoverBody"] * {{
    color: var(--text) !important;
}}
[data-testid="stPopoverBody"] .stCaption,
[data-testid="stPopoverBody"] .stCaption p {{
    color: var(--text2) !important;
}}
[data-testid="stPopoverBody"] .stTextInput > div > div > input {{
    background: var(--input-bg) !important;
    border-color: var(--border) !important;
    color: var(--text) !important;
}}
[data-testid="stPopoverBody"] .stSelectbox > div > div {{
    background: var(--input-bg) !important;
    border-color: var(--border) !important;
}}
[data-testid="stPopoverBody"] .stSelectbox [data-baseweb="select"] span {{
    color: var(--text) !important;
}}
[data-testid="stPopoverBody"] hr {{
    border-color: var(--border) !important;
    opacity: 0.6;
}}

/* ── Dataframe ── */
.stDataFrame {{ border-radius: 10px !important; border: 1px solid var(--border) !important; }}
[data-testid="stDataFrame"] > div {{ background: var(--card-bg) !important; }}
[data-testid="stDataFrame"] * {{ color: var(--text) !important; }}

/* ── Code blocks ── */
code, pre {{
    font-family: 'JetBrains Mono', 'Fira Code', monospace !important;
    font-size: 0.82rem !important;
}}
[data-testid="stCode"],
[data-testid="stCodeBlock"],
.stCodeBlock,
[data-testid="stCode"] > div,
[data-testid="stCodeBlock"] > div,
[data-testid="stCode"] pre,
[data-testid="stCodeBlock"] pre,
.stCodeBlock pre {{
    background: var(--surface) !important;
    background-color: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
}}
[data-testid="stCode"] pre,
[data-testid="stCodeBlock"] pre,
.stCodeBlock pre {{
    border: none !important;
}}
[data-testid="stCode"] code,
[data-testid="stCodeBlock"] code,
.stCodeBlock code {{
    color: var(--text) !important;
    background: transparent !important;
    background-color: transparent !important;
}}
[data-testid="stCode"] button,
[data-testid="stCodeBlock"] button {{
    background: var(--surface2) !important;
    background-color: var(--surface2) !important;
    border: 1px solid var(--border) !important;
    color: var(--text) !important;
    border-radius: 6px !important;
}}
[data-testid="stCode"] button svg,
[data-testid="stCodeBlock"] button svg {{
    fill: var(--text) !important;
}}
[data-testid="stCode"] button:hover,
[data-testid="stCodeBlock"] button:hover {{
    background: var(--accent) !important;
    background-color: var(--accent) !important;
    border-color: var(--accent) !important;
}}
[data-testid="stCode"] button:hover svg,
[data-testid="stCodeBlock"] button:hover svg {{
    fill: #ffffff !important;
}}
[data-testid="stCode"] pre::-webkit-scrollbar,
[data-testid="stCodeBlock"] pre::-webkit-scrollbar {{
    height: 6px;
    width: 6px;
}}
[data-testid="stCode"] pre::-webkit-scrollbar-track,
[data-testid="stCodeBlock"] pre::-webkit-scrollbar-track {{
    background: var(--surface);
}}
[data-testid="stCode"] pre::-webkit-scrollbar-thumb,
[data-testid="stCodeBlock"] pre::-webkit-scrollbar-thumb {{
    background: var(--surface2);
    border-radius: 3px;
}}

/* ── Status widget ── */
[data-testid="stStatus"] {{
    border-radius: 10px !important;
    border: 1px solid var(--border) !important;
    background: var(--card-bg) !important;
}}
[data-testid="stStatus"] * {{ color: var(--text) !important; }}
[data-testid="stStatus"] p {{ color: var(--text) !important; }}

/* ── Alerts ── */
.stAlert {{
    border-radius: 8px !important;
    border-left-width: 4px !important;
    background: var(--surface) !important;
}}
.stAlert p {{ color: var(--text) !important; }}
.stAlert [data-testid="stAlertContainer"] {{ background: var(--surface) !important; }}

/* ── Download button ── */
.stDownloadButton > button {{
    border-radius: 8px !important;
    font-weight: 600 !important;
    border: 1.5px solid var(--accent) !important;
    color: var(--accent) !important;
    background: transparent !important;
    transition: all 0.15s !important;
}}
.stDownloadButton > button:hover {{
    background: var(--accent) !important;
    color: #fff !important;
}}

/* ── Progress ── */
.stProgress > div > div > div > div {{
    background: linear-gradient(90deg, var(--accent), var(--accent2)) !important;
    border-radius: 999px !important;
}}

/* ── Divider ── */
hr {{
    border: none !important;
    border-top: 1px solid var(--border) !important;
    margin: 0.6rem 0 !important;
}}

/* ── Chips ── */
.chip {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: .76rem;
    font-weight: 600;
    border: 1px solid;
    font-family: 'Inter', sans-serif;
}}
.chip.ok  {{ background:rgba(78,201,176,.12); color:var(--success); border-color:rgba(78,201,176,.3); }}
.chip.bad {{ background:rgba(244,71,71,.12);  color:var(--error);   border-color:rgba(244,71,71,.3);  }}
.chip.fix {{ background:rgba(220,220,170,.12);color:var(--warning); border-color:rgba(220,220,170,.3);}}
.arrow {{ margin:0 5px; opacity:.4; color:var(--text2); }}

/* ── Model badge ── */
.mbadge {{
    display:inline-block; padding:2px 9px; border-radius:5px;
    font-size:0.72rem; font-weight:600;
    background:rgba(86,156,214,0.12); color:var(--accent);
    border:1px solid rgba(86,156,214,0.25); margin-top:4px;
}}

/* ── Hero ── */
.hero-wrap {{
    display:flex; align-items:center; justify-content:space-between;
    padding: 0.5rem 0 1rem;
    animation: slideDown 0.35s ease-out;
}}
.hero-left {{ display:flex; align-items:center; gap:13px; }}
.hero-logo {{ color:var(--accent); flex-shrink:0; }}
.hero-title {{
    font-size:1.7rem; font-weight:800;
    color:var(--text) !important; letter-spacing:-0.04em;
    margin:0; line-height:1.15;
}}
.hero-sub {{ font-size:0.82rem; color:var(--text2) !important; margin:3px 0 0; }}

/* ── Thin section divider ── */
.section-sep {{
    border: none;
    border-top: 1px solid var(--border);
    margin: 0 0 1rem;
}}

/* ── Flowchart (Fully responsive) ── */
.flow {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    max-width: 100%;
    padding: 0.85rem 0 1.1rem;
    gap: clamp(2px, 0.6vw, 6px);
    box-sizing: border-box;
}}
.fbox {{
    flex: 1 1 0px;
    min-width: 0;
    padding: clamp(6px, 1.1vw, 11px) clamp(3px, 1vw, 14px);
    border: 1.5px solid var(--border);
    border-radius: clamp(6px, 0.8vw, 10px);
    text-align: center;
    font-size: clamp(0.52rem, 0.44rem + 0.35vw, 0.76rem);
    font-weight: 600;
    color: var(--text);
    background: var(--card-bg);
    box-shadow: 0 1px 4px var(--shadow);
    white-space: normal;
    word-wrap: break-word;
    line-height: 1.3;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: clamp(38px, 4.5vw, 54px);
    transition: all 0.15s ease;
}}
.fbox.hi {{
    border-color: var(--accent) !important;
    color: var(--accent) !important;
    background: var(--accent-subtle) !important;
    font-weight: 700 !important;
}}
.farr {{
    font-size: clamp(0.65rem, 0.55rem + 0.4vw, 1rem);
    color: var(--text2);
    padding: 0 clamp(1px, 0.4vw, 8px);
    opacity: 0.55;
    flex-shrink: 0;
    line-height: 1;
    user-select: none;
}}

@media (max-width: 768px) {{
    .flow {{
        padding: 0.6rem 0 0.8rem;
    }}
    .fbox {{
        padding: 6px 3px;
        font-size: 0.62rem;
        line-height: 1.25;
        min-height: 42px;
    }}
    .farr {{
        padding: 0 2px;
        font-size: 0.75rem;
    }}
}}

@media (max-width: 520px) {{
    .flow {{
        padding: 0.4rem 0 0.6rem;
    }}
    .fbox {{
        padding: 5px 2px;
        font-size: 0.52rem;
        line-height: 1.2;
        min-height: 36px;
        border-width: 1px;
        border-radius: 6px;
    }}
    .farr {{
        padding: 0 1px;
        font-size: 0.6rem;
    }}
}}

@media (max-width: 380px) {{
    .fbox {{
        padding: 4px 1px;
        font-size: 0.45rem;
        line-height: 1.15;
        min-height: 30px;
        border-radius: 4px;
    }}
    .farr {{
        padding: 0;
        font-size: 0.5rem;
    }}
}}

/* ── DB section label ── */
.db-section-label {{
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--text2);
    margin-bottom: 0.5rem;
    display: block;
}}

/* ── Pop section label ── */
.pop-sep {{
    font-size: 0.68rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.1em;
    color: var(--text2); margin: 0.85rem 0 0.35rem; display: block;
}}

/* ── Example label ── */
.ex-label {{
    font-size: 0.68rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--text2); margin-bottom: 0.5rem; display: block;
}}

/* ── Loading animation ── */
@keyframes dotPulse {{
    0%, 80%, 100% {{ opacity: 0.15; transform: scale(0.8); }}
    40%            {{ opacity: 1;    transform: scale(1);   }}
}}
.loading-dots {{
    display: inline-flex; gap: 5px; align-items: center;
    vertical-align: middle; margin-left: 8px;
}}
.loading-dots span {{
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--accent); display: inline-block;
    animation: dotPulse 1.4s infinite ease-in-out;
}}
.loading-dots span:nth-child(2) {{ animation-delay: 0.2s; }}
.loading-dots span:nth-child(3) {{ animation-delay: 0.4s; }}
.loading-msg {{
    font-size: 0.9rem; font-weight: 500;
    color: var(--text); padding: 0.75rem 0 0.25rem;
}}

/* ── Results ── */
.result-wrap {{ animation: fadeUp 0.3s ease-out; }}

/* ── Animations ── */
@keyframes fadeUp {{
    from {{ opacity:0; transform:translateY(8px); }}
    to   {{ opacity:1; transform:translateY(0);   }}
}}
@keyframes slideDown {{
    from {{ opacity:0; transform:translateY(-6px); }}
    to   {{ opacity:1; transform:translateY(0);   }}
}}
</style>
""", unsafe_allow_html=True)


# ── SVG logo ──────────────────────────────────────────────────────────────────
DB_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 34 42" width="34" height="42">
  <ellipse cx="17" cy="8.5"  rx="15" ry="5.2" fill="currentColor" opacity="0.9"/>
  <rect    x="2"  y="8.5" width="30" height="25" fill="currentColor" opacity="0.62"/>
  <ellipse cx="17" cy="33.5" rx="15" ry="5.2" fill="currentColor" opacity="0.9"/>
  <ellipse cx="17" cy="8.5"  rx="15" ry="5.2" fill="none" stroke="white" stroke-width="0.7" opacity="0.22"/>
  <ellipse cx="17" cy="21"   rx="15" ry="5.2" fill="none" stroke="white" stroke-width="0.7" opacity="0.15"/>
</svg>"""


# Inject CSS and cleanup
inject_css(dark)
cleanup_old_uploads()

# ── Loading screen ────────────────────────────────────────────────────────────
if not st.session_state.get("_loaded"):
    _slot = st.empty()
    with _slot.container():
        _, _c, _ = st.columns([1, 2, 1])
        with _c:
            st.markdown(f"""
<div style="text-align:center;padding:3rem 1rem 1rem;">
  <div style="color:var(--accent);display:inline-block;margin-bottom:0.9rem;">{DB_SVG}</div>
  <h1 style="font-size:2rem;font-weight:800;letter-spacing:-0.04em;margin:0.15rem 0 0.1rem;color:var(--text);">QueryForge</h1>
  <p style="color:var(--text2);font-size:0.9rem;margin-bottom:2rem;">Natural language to SQL &mdash; powered by AI</p>
</div>
""", unsafe_allow_html=True)
            _bar = st.progress(0)
            _msg = st.empty()
            for _p, _t in [
                (0.15, "Loading schema retrieval engine..."),
                (0.38, "Initializing embedding model..."),
                (0.62, "Setting up LLM client..."),
                (0.82, "Preparing database utilities..."),
                (1.00, "Ready."),
            ]:
                _msg.caption(_t)
                _bar.progress(_p)
                time.sleep(0.25)
            time.sleep(0.15)
    _slot.empty()
    st.session_state["_loaded"] = True


# ── Helpers ───────────────────────────────────────────────────────────────────
@st.cache_resource
def demo_counter():
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
        if s == "retrieve_schema":   label, cls = "Schema retrieval", "ok"
        elif s == "generate":        label, cls = "Generate SQL", "ok"
        elif s == "execute":
            if h.get("soft"):        label, cls = "Execute: 0 rows", "fix"
            elif h["ok"]:            label, cls = "Execute", "ok"
            else:                    label, cls = "Execute: error", "bad"
        elif s == "look_at_data":    label, cls = "Look at data", "ok"
        else:                        label, cls = f"Correct #{h['attempt']}", "fix"
        parts.append(f'<span class="chip {cls}">{label}</span>')
    return '<span class="arrow">&#8594;</span>'.join(parts)


@st.cache_data
def all_example_questions(db_id):
    p = Path(config.SPIDER_DIR) / "dev.json"
    if not p.exists():
        return []
    try:
        dev = json.load(open(p, encoding="utf-8"))
        seen = set()
        out = []
        for x in dev:
            if x.get("db_id") == db_id:
                q = x.get("question", "").strip()
                if q and q not in seen:
                    seen.add(q)
                    out.append(q)
        return out
    except Exception:
        return []


def get_sample_questions(db_id, n=7):
    all_q = all_example_questions(db_id)
    if not all_q:
        return []
    if len(all_q) <= n:
        return all_q
    seed = st.session_state.get(f"_q_seed_{db_id}", 42)
    rng = random.Random(seed)
    return rng.sample(all_q, n)


def _provider_label_short(p: str) -> str:
    model = config.model_of(p)
    if p == "google":
        return model.replace("gemini-", "Gemini ").replace("-", " ").title() if model else "Gemini"
    return model if model else p.title()


def agent_report(r):
    hist  = r["history"]
    total = sum(h.get("seconds", 0) for h in hist)
    models = sorted({f"{h['llm']['model']} ({h['llm']['provider']})" for h in hist if h.get("llm")})
    fixes = sum(1 for h in hist if h["step"] == "correct")
    show  = st.session_state.get("show_prompts", False)
    who   = lambda h: h["llm"]["model"] if h.get("llm") else ""

    with st.expander(f"Agent trace  [{len(hist)} steps  |  {total:.1f}s  |  {fixes} correction(s)]"):
        st.caption(f"Model: {', '.join(models) or 'none called'}.  Corrections: {fixes}.")
        for i, h in enumerate(hist, 1):
            s, t = h["step"], f"{h.get('seconds', 0):.1f}s"
            if i > 1:
                st.divider()

            if s == "retrieve_schema":
                st.markdown(f"**{i}. Choose tables** &middot; {h.get('method','')} &middot; {t}")
                st.write(f"Sent {len(h['tables'])} of {h.get('total_tables', len(h['tables']))} tables: "
                         + ", ".join(h["tables"]))
                if h.get("picked"):       st.caption("Picked by model: " + ", ".join(h["picked"]))
                if h.get("added_by_fk"):  st.caption("Added via FK: "   + ", ".join(h["added_by_fk"]))
                if h.get("scores"):
                    st.caption("Scores: " + ", ".join(f"{k} {v}" for k, v in h["scores"].items()))
                if show and h.get("raw_answer"): st.code(h["raw_answer"], language="text")
                if show and h.get("prompt"):     st.code(h["prompt"],     language="text")

            elif s == "generate":
                st.markdown(f"**{i}. Write SQL** &middot; {who(h)} &middot; {t}")
                if h.get("note"): st.caption(h["note"])
                st.code(h["sql"], language="sql")
                if h.get("used_dictionary"):
                    st.caption("Prompt included database overview and table descriptions.")
                if show and h.get("prompt"): st.code(h["prompt"], language="text")

            elif s == "execute":
                if h.get("soft"):
                    st.markdown(f"**{i}. Run query** &middot; 0 rows, adjusting &middot; {t}")
                    if h.get("tried_relaxed"): st.caption("Case-insensitive version also returned 0 rows.")
                    for ev in h.get("evidence", []): st.caption(ev)
                elif h["ok"]:
                    st.markdown(f"**{i}. Run query** &middot; {h.get('rows')} rows &middot; {t}")
                    if h.get("relaxed_from"):
                        st.success("Exact matching returned 0 rows; retried case-insensitively. Original:")
                        st.code(h["relaxed_from"], language="sql")
                    elif h.get("rows") == 0:
                        st.warning("Query returned 0 rows. Check the SQL and filter values.")
                else:
                    st.markdown(f"**{i}. Run query** &middot; database error &middot; {t}")
                    st.code(h["error"], language="text")

            elif s == "look_at_data":
                st.markdown(f"**{i}. Look at the data** &middot; {t}")
                for line in h.get("found", []): st.caption(line.lstrip("- "))
                if not h.get("found"):      st.caption("No matching values found in chosen tables.")
                if h.get("enum_columns"):   st.caption(f"{h['enum_columns']} small-value columns listed.")
                if h.get("timed_out"):      st.caption("Search hit time limit; some columns skipped.")
                if show and h.get("notes"): st.code(h["notes"], language="text")
            else:
                st.markdown(f"**{i}. Correction attempt {h['attempt']}** &middot; {who(h)} &middot; {t}")
                st.caption("Model saw the failed query and error, then rewrote.")
                st.code(h["sql"], language="sql")
                if show and h.get("prompt"): st.code(h["prompt"], language="text")


def show_result(r):
    st.markdown('<div class="result-wrap">', unsafe_allow_html=True)
    st.markdown(chips(r["history"]), unsafe_allow_html=True)
    if r["error"]:
        st.error("The agent could not produce a working query. Last error:")
        st.code(r["error"])
    agent_report(r)
    t_ans, t_sql, t_sch = st.tabs(["Answer", "SQL", "Schema used"])
    with t_ans:
        if r["df"] is not None:
            st.dataframe(r["df"], use_container_width=True)
            if len(r["df"]) == 0:
                st.warning("No rows matched. Open the agent trace to investigate.")
            note = f"{len(r['df'])} rows"
            if r["more"]: note += f" (first {config.UI_ROW_LIMIT} shown)"
            st.caption(note)
            st.download_button("Download CSV", r["df"].to_csv(index=False), "result.csv", "text/csv")
    with t_sql:
        st.code(r["sql"], language="sql")
        st.caption("Generated SQL can be wrong. Verify it against your question.")
    with t_sch:
        st.write("Tables sent to the model:", ", ".join(r["tables"]))
        st.code(r["schema_text"], language="sql")
    st.markdown('</div>', unsafe_allow_html=True)


def overview_panel(db_id, provider, api_key):
    try:
        n = dictionary.table_count(db_id)
    except Exception:
        return
    d       = dictionary.load_cached(db_id)
    persist = not (config.PUBLIC_MODE and db_id.startswith("upload_"))
    needed  = math.ceil(n / config.DICT_BATCH_TABLES) + 1
    auto    = (not config.PUBLIC_MODE) and n >= config.DICT_AUTO_MIN_TABLES

    with st.expander("Database overview", expanded=False):
        if d is None:
            if db_id.startswith("upload_"):
                if config.PUBLIC_MODE and not api_key:
                    st.info(f"Add your API key in Settings to build an overview ({needed} model calls).")
                else:
                    if not auto:
                        st.caption("Optional. Helps most on databases with many tables.")
                    clicked = st.button(f"Build overview ({needed} model calls)", key=f"build_{db_id}")
                    tried   = st.session_state.get(f"tried_{db_id}", False)
                    if clicked or (auto and not tried):
                        st.session_state[f"tried_{db_id}"] = True
                        bar = st.progress(0.0, text="Starting...")
                        try:
                            d = dictionary.build(
                                db_id, provider, api_key, persist=persist,
                                progress=lambda done, total, msg: bar.progress(
                                    min(done / total, 1.0), text=msg))
                        except Exception as e:
                            st.error(f"Could not build overview: {str(e)[:300]}")
                        bar.empty()
            else:
                st.caption("No overview available for this database.")

        if d is not None:
            if d.get("overview"): st.write(d["overview"])
            for a in d.get("areas", []): st.markdown(f"- {a}")
            st.caption(
                f"{len(d['tables'])} of {d['n_tables']} tables described by "
                f"{d.get('model') or 'the model'}. Descriptions can be wrong.")
            if d.get("notes"):
                st.markdown("**Model notes:**\n" + "\n".join(f"- {x}" for x in d["notes"]))
            st.dataframe(
                pd.DataFrame([{"table": t, "description": v} for t, v in d["tables"].items()]),
                height=240, use_container_width=True)
            if db_id.startswith("upload_") and st.button("Rebuild overview", key=f"rebuild_{db_id}"):
                dictionary.forget(db_id, delete_disk=True)
                st.session_state.pop(f"tried_{db_id}", None)
                st.rerun()


def explore_database_panel(db_id, provider, api_key):
    if not db_id:
        st.info("Please select or upload a database above to explore its schema and tables.")
        return

    try:
        schema = get_schema(db_id, n_samples=3)
    except Exception as e:
        st.error(f"Could not load database schema: {e}")
        return

    tables = sorted(schema.keys())
    if not tables:
        st.warning("This database has no tables.")
        return

    # 1. Database Overview & Descriptions
    d = dictionary.load_cached(db_id)
    if d and d.get("overview"):
        st.markdown(f"**About this database:** {d['overview']}")
        if d.get("areas"):
            st.caption("Key domains: " + " &middot; ".join(d["areas"]))
    elif not d and db_id.startswith("upload_"):
        n = len(tables)
        needed = math.ceil(n / config.DICT_BATCH_TABLES) + 1
        persist = not (config.PUBLIC_MODE and db_id.startswith("upload_"))
        if config.PUBLIC_MODE and not api_key:
            st.info(f"Optional: Add your API key in Settings to generate AI table descriptions for this database ({needed} model calls).")
        else:
            if st.button(f"Generate AI Table Descriptions ({needed} model calls)", key=f"exp_build_{db_id}"):
                bar = st.progress(0.0, text="Generating table descriptions...")
                try:
                    d = dictionary.build(
                        db_id, provider, api_key, persist=persist,
                        progress=lambda done, total, msg: bar.progress(min(done / total, 1.0), text=msg))
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not build overview: {str(e)[:300]}")
                bar.empty()

    st.markdown('<hr class="section-sep">', unsafe_allow_html=True)

    # 2. Table Selector + Stats
    col_sel, col_stat = st.columns([2, 1])
    with col_sel:
        selected_table = st.selectbox("Choose a table to inspect:", tables, key=f"_exp_t_{db_id}")

    path = get_db_path(db_id)
    row_count = 0
    preview_rows = []
    col_names = []
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        cur = conn.cursor()
        row_count = cur.execute(f'SELECT COUNT(*) FROM "{selected_table}"').fetchone()[0]
        cur.execute(f'SELECT * FROM "{selected_table}" LIMIT 10')
        col_names = [desc[0] for desc in cur.description] if cur.description else []
        preview_rows = cur.fetchall()
        conn.close()
    except Exception as e:
        st.warning(f"Could not read table '{selected_table}': {e}")

    with col_stat:
        st.markdown(
            f"<div style='padding-top:1.8rem; font-size:0.85rem; font-weight:600; color:var(--text2);'>"
            f"Total tables: <b>{len(tables)}</b> &nbsp;|&nbsp; Rows in <code>{selected_table}</code>: <b>{row_count}</b></div>",
            unsafe_allow_html=True
        )

    # 3. Table description from data dictionary
    if d and d.get("tables", {}).get(selected_table):
        st.info(f"**Table Purpose:** {d['tables'][selected_table]}")

    # 4. Data Preview & Column Schema Tabs
    t_prev, t_schema = st.tabs([f"Data Preview ({min(10, row_count)} of {row_count} rows)", "Columns & Schema"])

    with t_prev:
        if preview_rows:
            df_prev = pd.DataFrame(preview_rows, columns=unique(col_names))
            st.dataframe(df_prev, use_container_width=True)
            if row_count > 10:
                st.caption(f"Showing first 10 rows of {row_count} total rows.")
        else:
            st.info(f"Table '{selected_table}' is currently empty (0 rows).")

    with t_schema:
        t_info = schema.get(selected_table, {})
        cols_meta = []
        fks_map = {fk["from"]: f"{fk['ref_table']}.{fk['to']}" for fk in t_info.get("fks", [])}
        for c in t_info.get("columns", []):
            cname = c["name"]
            cols_meta.append({
                "Column": cname,
                "Data Type": c["type"] or "TEXT",
                "Primary Key": "Yes" if c.get("pk") else "No",
                "Foreign Key": f"{fks_map[cname]}" if cname in fks_map else "-",
            })
        if cols_meta:
            st.dataframe(pd.DataFrame(cols_meta), use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN PAGE
# ═══════════════════════════════════════════════════════════════════════════════
accent_hex = "#569cd6" if dark else "#4f46e5"

# ── Hero + Settings (same row) ────────────────────────────────────────────────
_hcol, _scol = st.columns([5, 1])

with _hcol:
    st.markdown(f"""
<div class="hero-wrap">
  <div class="hero-left">
    <div class="hero-logo" style="color:{accent_hex};">{DB_SVG}</div>
    <div>
      <p class="hero-title">QueryForge</p>
      <p class="hero-sub">Natural language to SQL &mdash; powered by AI</p>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

with _scol:
    st.markdown("<div style='padding-top:0.6rem;'>", unsafe_allow_html=True)

    # ── Settings popover ──────────────────────────────────────────────────────
    with st.popover("Settings", use_container_width=True):

        # Appearance
        st.markdown('<span class="pop-sep">Appearance</span>', unsafe_allow_html=True)
        _new_dark = st.toggle("Dark mode", value=st.session_state["dark_mode"], key="_pop_dark")
        if _new_dark != st.session_state["dark_mode"]:
            st.session_state["dark_mode"] = _new_dark
            st.rerun()

        # Model
        st.markdown('<span class="pop-sep">Model</span>', unsafe_allow_html=True)
        _avail = _available_providers()
        if _avail:
            _opt_vals   = [None] + _avail
            _opt_labels = ["Auto (chain order)"] + [_provider_label(p) for p in _avail]
            _cur_pin    = st.session_state.get("pinned_provider")
            _cur_idx    = _opt_vals.index(_cur_pin) if _cur_pin in _opt_vals else 0
            _sel_idx = st.selectbox(
                "Provider", options=range(len(_opt_vals)),
                format_func=lambda i: _opt_labels[i],
                index=_cur_idx, key="_pop_provider",
                label_visibility="collapsed",
            )
            st.session_state["pinned_provider"] = _opt_vals[_sel_idx]
            if _opt_vals[_sel_idx]:
                _mn = config.model_of(_opt_vals[_sel_idx])
                if _mn:
                    st.markdown(f'<span class="mbadge">{_mn}</span>', unsafe_allow_html=True)
        else:
            st.caption("No models configured in .env")

        # API Key Override
        st.markdown('<span class="pop-sep">API Key Override</span>', unsafe_allow_html=True)
        st.caption("Enter your own key to override the server key. Kept in session only, never saved.")
        _avail_for_key = _avail if _avail else _ALL_PROVIDERS
        _kp_labels = [_provider_label(p) for p in _avail_for_key]
        _kp_idx = st.selectbox(
            "Key provider", options=range(len(_avail_for_key)),
            format_func=lambda i: _kp_labels[i],
            key="_pop_key_provider", label_visibility="collapsed",
        )
        st.session_state["custom_key_provider"] = _avail_for_key[_kp_idx]
        _custom_key = st.text_input(
            "API key", type="password",
            value=st.session_state.get("custom_api_key", ""),
            key="_pop_api_key",
            placeholder="Paste API key here...",
        )
        st.session_state["custom_api_key"] = _custom_key.strip()
        if st.session_state["custom_api_key"]:
            st.success("Custom key active for this session.")

        # Agent
        st.markdown('<span class="pop-sep">Agent</span>', unsafe_allow_html=True)
        st.session_state["max_retries"] = st.slider(
            "Self-correction attempts", 0, 3, st.session_state["max_retries"], key="_pop_retries")
        st.session_state["show_prompts"] = st.toggle(
            "Show full prompts in agent trace", value=st.session_state["show_prompts"], key="_pop_prompts")
        st.session_state["look_at_data"] = st.toggle(
            "Look at data values when query returns nothing",
            value=st.session_state["look_at_data"], key="_pop_look",
            help="Reads real values from DB and sends them to the AI to help fix queries.")

        if config.PUBLIC_MODE:
            st.markdown('<span class="pop-sep">Demo quota</span>', unsafe_allow_html=True)
            _left = max(config.DEMO_QUESTIONS_PER_SESSION - st.session_state["asked"], 0)
            st.caption(f"Free demo questions remaining: **{_left}**")

    st.markdown("</div>", unsafe_allow_html=True)

# Thin separator (just 1px, no 3D)
st.markdown('<hr class="section-sep">', unsafe_allow_html=True)

# Resolve provider + api_key
_pinned   = st.session_state.get("pinned_provider")
_cust_key = st.session_state.get("custom_api_key", "")
_cust_prov = st.session_state.get("custom_key_provider")

if _cust_key:
    provider = _cust_prov
    api_key  = _cust_key
elif _pinned:
    provider = _pinned
    api_key  = None
else:
    provider = None
    api_key  = None

max_retries = st.session_state["max_retries"]

# ── Pipeline flowchart ────────────────────────────────────────────────────────
st.markdown("""
<div class="flow">
  <div class="fbox">Natural Language<br>Query</div>
  <span class="farr">&#8594;</span>
  <div class="fbox">Schema<br>Retrieval</div>
  <span class="farr">&#8594;</span>
  <div class="fbox hi">SQL<br>Generation</div>
  <span class="farr">&#8594;</span>
  <div class="fbox">Database<br>Execution</div>
  <span class="farr">&#8594;</span>
  <div class="fbox">Results &amp;<br>Validation</div>
</div>
""", unsafe_allow_html=True)

# ── Database selection ────────────────────────────────────────────────────────
st.markdown('<span class="db-section-label">Database</span>', unsafe_allow_html=True)

_dc1, _dc2 = st.columns([1, 3])
with _dc1:
    source = st.radio("Database source", ["Sample database", "Upload your own"],
                      label_visibility="collapsed")
db_id = None
with _dc2:
    if source == "Sample database":
        sample_dir = Path(config.SPIDER_DIR) / "database"
        curated_list = [
            "concert_singer",
            "world_1",
            "car_1",
            "flight_2",
            "student_transcripts_tracking",
            "tvshow",
            "network_1",
            "pets_1",
            "orchestra",
            "employee_hire_evaluation",
        ]
        available_curated = [d for d in curated_list if (sample_dir / d).is_dir()] if sample_dir.exists() else []
        samples = available_curated if available_curated else (
            sorted(p.name for p in sample_dir.iterdir() if p.is_dir()) if sample_dir.exists() else []
        )
        if samples:
            db_id = st.selectbox(
                "Choose a database",
                samples,
                index=None,
                placeholder="Choose a database...",
            )
        else:
            st.info(f"No sample databases found in `{sample_dir}`. Switch to **Upload your own** to query any SQLite file.")
    else:
        st.caption(
            "**Sent to AI:** question, table/column names, types, generated descriptions, SQL errors.  "
            "**Not sent:** actual row data.  "
            f"Files deleted after ~{config.UPLOAD_TTL_MIN} min.")
        up = st.file_uploader("SQLite file", type=["sqlite", "sqlite3", "db"])
        if up is not None:
            sig = (up.name, up.size)
            uid = st.session_state.get("upload_id")
            if st.session_state.get("upload_sig") != sig or not (uid and get_db_path(uid).exists()):
                delete_upload(uid)
                uid, err = save_upload(up.getvalue())
                st.session_state["upload_id"], st.session_state["upload_sig"] = uid, sig
                if err: st.error(err)
            db_id = uid
        else:
            delete_upload(st.session_state.pop("upload_id", None))
            st.session_state.pop("upload_sig", None)

st.markdown("<div style='margin-bottom:0.5rem'></div>", unsafe_allow_html=True)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_ask, tab_explore = st.tabs(["Ask", "Explore Database"])

with tab_ask:
    if db_id:
        overview_panel(db_id, provider, api_key)
    else:
        st.info("Please select or upload a database above to get started.")

    # Full-width query form
    with st.form("query_form", enter_to_submit=True, border=False):
        question = st.text_input(
            "Your question",
            key="q",
            placeholder="e.g.  How many singers are there?",
        )
        _run_col, _space = st.columns([1, 5])
        with _run_col:
            go = st.form_submit_button("Run", type="primary", disabled=not db_id)

    # Example questions (7 random questions in a 2-column grid with shuffle)
    if db_id and source == "Sample database":
        exs = get_sample_questions(db_id, n=7)
        if exs:
            _hcol, _bcol = st.columns([5, 1])
            with _hcol:
                st.markdown('<span class="ex-label">Example questions (click to ask)</span>', unsafe_allow_html=True)
            with _bcol:
                if st.button("Shuffle", key=f"shuf_{db_id}", help="Pick 7 different random questions from dev.json", use_container_width=True):
                    st.session_state[f"_q_seed_{db_id}"] = st.session_state.get(f"_q_seed_{db_id}", 0) + 1
                    st.rerun()

            col1, col2 = st.columns(2)
            seed = st.session_state.get(f"_q_seed_{db_id}", 0)
            for i, eq in enumerate(exs):
                target_col = col1 if i % 2 == 0 else col2
                with target_col:
                    st.button(
                        eq,
                        key=f"ex_{db_id}_{i}_{seed}",
                        on_click=lambda q=eq: st.session_state.update(q=q),
                        use_container_width=True,
                    )
    elif db_id and source != "Sample database":
        st.caption("Custom database active. Switch to the **Explore Database** tab above to view your tables, columns, and data.")

    # ── Run logic ─────────────────────────────────────────────────────────────
    if go:
        # Clear previous result immediately to prevent ghost display
        st.session_state.pop("result", None)

        if not question.strip():
            st.warning("Please enter a question before running.")
            st.stop()

        blocked = None
        if config.PUBLIC_MODE and not api_key:
            if st.session_state["asked"] >= config.DEMO_QUESTIONS_PER_SESSION:
                blocked = "You have used your free demo questions. Add your API key in Settings."
            elif not use_demo_slot():
                blocked = "Today's shared demo allowance is used up. Add your API key in Settings, or try tomorrow."
        if blocked:
            st.warning(blocked)
        else:
            if config.PUBLIC_MODE and not api_key:
                st.session_state["asked"] += 1
            try:
                get_db_path(db_id).touch()
                n_tables = len(get_schema(db_id))
            except Exception:
                st.error("Could not read this database.")
                st.stop()

            # Animated loading placeholder
            _loading = st.empty()
            _loading.markdown("""
<div class="loading-msg">
  Analysing your question
  <span class="loading-dots"><span></span><span></span><span></span></span>
</div>
""", unsafe_allow_html=True)

            use_retrieval = n_tables > config.SKIP_RETRIEVAL_BELOW
            state = {"history": [], "sql": "", "error": None, "tables": [], "schema_text": ""}
            try:
                _loading.empty()
                with st.status("Working on it...", expanded=True) as status:
                    for node, update in stream_agent(
                        question.strip(), db_id, use_retrieval, max_retries,
                        config.RETRIEVAL_K, provider, api_key,
                        picker       = n_tables > config.PICKER_MIN_TABLES,
                        robust       = True,
                        look_at_data = st.session_state.get("look_at_data", False),
                    ):
                        state.update(update)
                        if node == "retrieve_schema":
                            h = update["history"][-1]
                            st.write(f"Schema retrieval: {h.get('method','')}, "
                                     f"using {len(update['tables'])} of {n_tables} tables")
                        elif node == "generate":
                            st.write("SQL query generated")
                        elif node == "execute":
                            h = update["history"][-1]
                            if h.get("soft"):
                                st.write("Query returned 0 rows — adjusting filters...")
                            elif h.get("relaxed_from"):
                                st.write(f"Retried case-insensitively: {h['rows']} rows.")
                            elif update["error"] is None:
                                st.write(f"Query executed successfully ({h['rows']} rows)")
                            else:
                                st.write(f"Database error: {update['error']}")
                        elif node == "ground":
                            st.write("Looking up how values are stored in the data...")
                        elif node == "correct":
                            st.write(f"Correction attempt {update['retry_count']}: rewriting query...")

                    last_exec = next(
                        (h for h in reversed(state["history"]) if h["step"] == "execute"), None)
                    if last_exec and last_exec.get("soft"):
                        state["error"] = None
                    ok = state["error"] is None
                    status.update(
                        label    = "Done" if ok else "Could not produce a working query",
                        state    = "complete" if ok else "error",
                        expanded = False,
                    )
            except Exception as e:
                st.error(f"AI provider error: {str(e)[:300]}")
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

    # Show result (only if it belongs to the currently selected db)
    r = st.session_state.get("result")
    if r and r["db_id"] == db_id:
        show_result(r)

with tab_explore:
    explore_database_panel(db_id, provider, api_key)
