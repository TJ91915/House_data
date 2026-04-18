"""Shared helpers for the multi-page House dashboard: auth, palette, chart styling."""
from __future__ import annotations

from pathlib import Path

import gspread
import plotly.graph_objects as go
import streamlit as st
from google.oauth2.service_account import Credentials

# Sheet IDs
SHEET_ID_ENERGY = "1stKNr_MzA3fJL3kKSofMqxK4Nu66XbVtqsLzyosKqpQ"
SHEET_ID_TEMP   = "1ZOiXI_23xaTC7QAT6Z_l7v6H9KefbzTqM0UI5c7bDB0"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
LOCAL_KEY = Path(__file__).parent / "service-account-key.json"

# ---------- palette (shared across pages) ----------
C_ENERGY    = "#6B9A8E"   # muted teal/sage
C_STANDING  = "#D4C5A9"   # soft tan
C_KWH       = "#C07855"   # muted terracotta
C_ROLLING   = "#7E6B8F"   # dusty plum
C_TEXT      = "#2F3640"   # soft charcoal
C_GRID      = "#D8D1C3"   # faint sandstone

C_TEMP_MIN  = "#7E9FBD"   # cool blue
C_TEMP_MEAN = "#7B9B7E"   # sage
C_TEMP_MAX  = "#C07855"   # warm terracotta
C_TEMP_RIBBON = "rgba(123, 155, 126, 0.18)"

HEAT_SCALE      = [[0, "#F3EADB"], [0.5, "#D49A6A"], [1, "#A84F2C"]]
HEAT_SCALE_TEMP = [[0, "#7E9FBD"], [0.5, "#F0E6D6"], [1, "#C07855"]]  # cool→warm


# ---------- auth ----------
def credentials() -> Credentials:
    """Prefer Streamlit secrets (cloud); fall back to local JSON key."""
    try:
        info = dict(st.secrets["gcp_service_account"])
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    except (KeyError, FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        pass
    if LOCAL_KEY.exists():
        return Credentials.from_service_account_file(str(LOCAL_KEY), scopes=SCOPES)
    raise RuntimeError(
        "No credentials. Put service-account-key.json in project root, "
        "or configure [gcp_service_account] in .streamlit/secrets.toml."
    )


def client() -> gspread.Client:
    return gspread.authorize(credentials())


def style(fig: go.Figure) -> go.Figure:
    """Apply the shared soft-theme layout to any Plotly figure."""
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=C_TEXT, family="sans-serif", size=13),
        title=dict(font=dict(size=15, color=C_TEXT)),
    )
    fig.update_xaxes(gridcolor=C_GRID, linecolor=C_GRID, zerolinecolor=C_GRID)
    fig.update_yaxes(gridcolor=C_GRID, linecolor=C_GRID, zerolinecolor=C_GRID)
    return fig
