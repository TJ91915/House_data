"""Shared helpers for the multi-page House dashboard: auth, palette, chart styling, loaders."""
from __future__ import annotations

from pathlib import Path

import gspread
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from google.oauth2.service_account import Credentials

CACHE_TTL = 7200  # 2 hours

# Sheet IDs
SHEET_ID_ENERGY = "1stKNr_MzA3fJL3kKSofMqxK4Nu66XbVtqsLzyosKqpQ"
SHEET_ID_TEMP   = "1ZOiXI_23xaTC7QAT6Z_l7v6H9KefbzTqM0UI5c7bDB0"
SHEET_ID_MOTION = "1rL54qg6g1eOxGZTWWkflqRFpE7QbFF11TUXyUhh6ov4"
SHEET_ID_WATER  = "1yoHfWhVb-g5blWnULsslQv1enkup48pRzbpRWX26ixo"

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

C_WATER     = "#6B8DA8"   # muted slate-blue (cold water)
# Reserved for future Hot Water dataset:
# C_HOT_WATER = "#C28B6E"   # warm copper

HEAT_SCALE       = [[0, "#F3EADB"], [0.5, "#D49A6A"], [1, "#A84F2C"]]
HEAT_SCALE_TEMP  = [[0, "#7E9FBD"], [0.5, "#F0E6D6"], [1, "#C07855"]]  # cool→warm
HEAT_SCALE_WATER = [[0, "#F3EADB"], [0.5, "#9BB8CC"], [1, "#3B6884"]]  # cream→deep slate


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


# ---------- data loaders (cached, shared across pages) ----------
@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading energy data…")
def load_energy() -> pd.DataFrame:
    ws = client().open_by_key(SHEET_ID_ENERGY).worksheet("Energy_1")
    rows = ws.get_all_values()
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df = df[["Consumption (kwh)", "Start"]].copy()
    df["start"] = pd.to_datetime(df["Start"], errors="coerce")
    df["kwh"] = pd.to_numeric(df["Consumption (kwh)"], errors="coerce")
    df = df.dropna(subset=["start", "kwh"]).sort_values("start").reset_index(drop=True)
    df["date"] = df["start"].dt.date
    df["hhmm"] = df["start"].dt.strftime("%H:%M")
    df["weekday"] = df["start"].dt.weekday
    return df[["start", "date", "hhmm", "weekday", "kwh"]]


@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading tariffs…")
def load_tariffs() -> pd.DataFrame:
    ws = client().open_by_key(SHEET_ID_ENERGY).worksheet("Tariffs")
    rows = ws.get_all_values()
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df = df[df["Valid From"].str.strip() != ""].copy()
    df["valid_from"] = pd.to_datetime(df["Valid From"])
    df["unit_rate_p"] = pd.to_numeric(df["Unit Rate (p/kWh inc VAT)"])
    df["standing_p_day"] = pd.to_numeric(df["Standing Charge (p/day inc VAT)"])
    return df[["valid_from", "unit_rate_p", "standing_p_day"]].sort_values("valid_from")


@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading temperature data…")
def load_temperature() -> pd.DataFrame:
    ws = client().open_by_key(SHEET_ID_TEMP).worksheet("Temperature")
    rows = ws.get_all_values()
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df = df[["Timestamp", "Temp_c"]].copy()
    df["ts"] = pd.to_datetime(df["Timestamp"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
    df["temp_c"] = pd.to_numeric(df["Temp_c"], errors="coerce")
    df = df.dropna(subset=["ts", "temp_c"]).sort_values("ts").reset_index(drop=True)
    df["date"] = df["ts"].dt.date
    df["hour"] = df["ts"].dt.hour
    df["weekday"] = df["ts"].dt.weekday
    return df[["ts", "date", "hour", "weekday", "temp_c"]]


@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading motion data…")
def load_motion() -> pd.DataFrame:
    """Union both motion-log tabs (old + new form), filter to Yes-only events."""
    sh = client().open_by_key(SHEET_ID_MOTION)
    frames = []
    for tab in ("Old form", "New form"):
        rows = sh.worksheet(tab).get_all_values()
        if not rows:
            continue
        frames.append(pd.DataFrame(rows[1:], columns=rows[0]))
    df = pd.concat(frames, ignore_index=True)
    # Column has a trailing space in the sheet header; some values have trailing space too.
    motion_col = next(c for c in df.columns if c.strip().lower().startswith("motion"))
    df = df.rename(columns={motion_col: "motion", "Timestamp": "ts_raw"})
    df["motion"] = df["motion"].str.strip().str.lower()
    df = df[df["motion"] == "yes"].copy()
    df["ts"] = pd.to_datetime(df["ts_raw"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
    df = df.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    df["date"] = df["ts"].dt.date
    df["hour"] = df["ts"].dt.hour
    df["weekday"] = df["ts"].dt.weekday
    return df[["ts", "date", "hour", "weekday"]]


@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading water data…")
def load_water() -> pd.DataFrame:
    """Daily water meter readings + per-day consumption (one row per day)."""
    ws = client().open_by_key(SHEET_ID_WATER).worksheet("Water")
    rows = ws.get_all_values()
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df["date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y", errors="coerce")
    df["meter_l"] = pd.to_numeric(df["Meter read"], errors="coerce")
    df["cons_l"] = pd.to_numeric(df["Consumption in Litres"], errors="coerce")
    df["cons_m3"] = pd.to_numeric(df["Consumption Cubic meter"], errors="coerce")
    df = df.dropna(subset=["date", "cons_l"]).sort_values("date").reset_index(drop=True)
    df["weekday"] = df["date"].dt.weekday
    return df[["date", "weekday", "meter_l", "cons_l", "cons_m3"]]


def join_cost(energy: pd.DataFrame, tariffs: pd.DataFrame) -> pd.DataFrame:
    """Attach unit rate + standing per slot. Cost in £. Pure function — not cached."""
    out = pd.merge_asof(
        energy.sort_values("start"),
        tariffs.rename(columns={"valid_from": "start"}),
        on="start",
        direction="backward",
    )
    out["energy_cost_p"] = out["kwh"] * out["unit_rate_p"]
    out["standing_p_slot"] = out["standing_p_day"] / 48
    out["cost_gbp"] = (out["energy_cost_p"] + out["standing_p_slot"]) / 100
    out["energy_gbp"] = out["energy_cost_p"] / 100
    out["standing_gbp"] = out["standing_p_slot"] / 100
    return out
