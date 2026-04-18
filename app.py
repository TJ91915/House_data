"""Energy dashboard — reads Google Sheets, shows kWh and cost."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import gspread
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from google.oauth2.service_account import Credentials

SHEET_ID = "1stKNr_MzA3fJL3kKSofMqxK4Nu66XbVtqsLzyosKqpQ"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
LOCAL_KEY = Path(__file__).parent / "service-account-key.json"

# Palette — warm, muted, matches .streamlit/config.toml
C_ENERGY   = "#6B9A8E"   # muted teal / sage
C_STANDING = "#D4C5A9"   # soft tan
C_KWH      = "#C07855"   # muted terracotta
C_ROLLING  = "#7E6B8F"   # dusty plum
C_TEXT     = "#2F3640"   # soft charcoal
C_GRID     = "#D8D1C3"   # faint sandstone
HEAT_SCALE = [[0, "#F3EADB"], [0.5, "#D49A6A"], [1, "#A84F2C"]]


def _style(fig: go.Figure) -> go.Figure:
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


# ---------- auth ----------
def _credentials() -> Credentials:
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


def _client() -> gspread.Client:
    return gspread.authorize(_credentials())


# ---------- data ----------
@st.cache_data(ttl=3600, show_spinner="Loading energy data…")
def load_energy() -> pd.DataFrame:
    ws = _client().open_by_key(SHEET_ID).worksheet("Energy_1")
    rows = ws.get_all_values()
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df = df[["Consumption (kwh)", "Start"]].copy()
    df["start"] = pd.to_datetime(df["Start"], errors="coerce")
    df["kwh"] = pd.to_numeric(df["Consumption (kwh)"], errors="coerce")
    df = df.dropna(subset=["start", "kwh"]).sort_values("start").reset_index(drop=True)
    df["date"] = df["start"].dt.date
    df["hhmm"] = df["start"].dt.strftime("%H:%M")
    df["weekday"] = df["start"].dt.weekday  # 0=Mon
    return df[["start", "date", "hhmm", "weekday", "kwh"]]


@st.cache_data(ttl=3600, show_spinner="Loading tariffs…")
def load_tariffs() -> pd.DataFrame:
    ws = _client().open_by_key(SHEET_ID).worksheet("Tariffs")
    rows = ws.get_all_values()
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df = df[df["Valid From"].str.strip() != ""].copy()
    df["valid_from"] = pd.to_datetime(df["Valid From"])
    df["unit_rate_p"] = pd.to_numeric(df["Unit Rate (p/kWh inc VAT)"])
    df["standing_p_day"] = pd.to_numeric(df["Standing Charge (p/day inc VAT)"])
    return df[["valid_from", "unit_rate_p", "standing_p_day"]].sort_values("valid_from")


def join_cost(energy: pd.DataFrame, tariffs: pd.DataFrame) -> pd.DataFrame:
    """Attach unit rate + standing per slot. Cost in £."""
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


# ---------- aggregation helpers ----------
def daily(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("date").agg(
        kwh=("kwh", "sum"),
        cost_gbp=("cost_gbp", "sum"),
        energy_gbp=("energy_gbp", "sum"),
        standing_gbp=("standing_gbp", "sum"),
    ).reset_index()
    g["date"] = pd.to_datetime(g["date"])
    return g


def resample(df_daily: pd.DataFrame, freq: str) -> pd.DataFrame:
    """freq: 'D' day, 'W' week, 'MS' month."""
    return (
        df_daily.set_index("date")
        .resample(freq)
        .sum(numeric_only=True)
        .reset_index()
    )


def baseload_kwh_per_day(df: pd.DataFrame) -> float:
    """Mean kWh/slot between 01:00 and 04:30, × 48 → kWh/day."""
    mask = (df["hhmm"] >= "01:00") & (df["hhmm"] <= "04:30")
    slot_mean = df.loc[mask, "kwh"].mean()
    return float(slot_mean * 48) if pd.notna(slot_mean) else 0.0


# ---------- charts ----------
def chart_daily(df_daily: pd.DataFrame, freq: str) -> go.Figure:
    d = resample(df_daily, freq)
    label = {"D": "Daily", "W": "Weekly", "MS": "Monthly"}[freq]
    fig = go.Figure()
    fig.add_bar(x=d["date"], y=d["energy_gbp"], name="Energy (£)", marker_color=C_ENERGY)
    fig.add_bar(x=d["date"], y=d["standing_gbp"], name="Standing (£)", marker_color=C_STANDING)
    fig.add_scatter(
        x=d["date"], y=d["kwh"], name="kWh", yaxis="y2",
        mode="lines", line=dict(color=C_KWH, width=2),
    )
    if freq == "D" and len(d) >= 7:
        d = d.assign(kwh_7=d["kwh"].rolling(7, min_periods=1).mean())
        fig.add_scatter(
            x=d["date"], y=d["kwh_7"], name="kWh 7-day avg", yaxis="y2",
            mode="lines", line=dict(color=C_ROLLING, width=2, dash="dot"),
        )
    fig.update_layout(
        title=f"{label} cost (£) and consumption (kWh)",
        barmode="stack",
        yaxis=dict(title="£", rangemode="tozero"),
        yaxis2=dict(title="kWh", overlaying="y", side="right", rangemode="tozero", showgrid=False),
        xaxis=dict(title=""),
        legend=dict(orientation="h", y=-0.15),
        height=420,
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return _style(fig)


def chart_calendar_heatmap(df_daily: pd.DataFrame) -> go.Figure:
    d = df_daily.copy()
    d["dow"] = d["date"].dt.weekday  # 0=Mon
    d["week"] = d["date"] - pd.to_timedelta(d["dow"], unit="d")
    pivot = d.pivot_table(index="dow", columns="week", values="kwh", aggfunc="sum")
    pivot = pivot.reindex(range(7))
    dow_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=[c.strftime("%Y-%m-%d") for c in pivot.columns],
            y=dow_labels,
            colorscale=HEAT_SCALE,
            colorbar=dict(title="kWh/day"),
            hovertemplate="Week of %{x}<br>%{y}<br>%{z:.2f} kWh<extra></extra>",
        )
    )
    fig.update_layout(
        title="Daily kWh — calendar heatmap",
        height=320,
        margin=dict(l=40, r=40, t=60, b=40),
        yaxis=dict(autorange="reversed"),
    )
    return _style(fig)


def chart_time_of_day(df: pd.DataFrame) -> go.Figure:
    d = df.copy()
    d["is_weekend"] = d["weekday"] >= 5
    agg = (
        d.groupby(["hhmm", "is_weekend"])["kwh"]
        .mean()
        .reset_index()
        .rename(columns={"kwh": "avg_kwh"})
    )
    agg["kind"] = np.where(agg["is_weekend"], "Weekend", "Weekday")
    fig = px.line(
        agg, x="hhmm", y="avg_kwh", color="kind",
        title="Average kWh by half-hour — weekday vs weekend",
        labels={"hhmm": "Time of day", "avg_kwh": "Avg kWh/slot", "kind": ""},
        color_discrete_map={"Weekday": C_ENERGY, "Weekend": C_KWH},
    )
    fig.update_traces(line=dict(width=2))
    ticks = [f"{h:02d}:00" for h in range(0, 24, 2)]
    fig.update_xaxes(tickmode="array", tickvals=ticks)
    fig.update_layout(height=380, margin=dict(l=40, r=40, t=60, b=40),
                      legend=dict(orientation="h", y=-0.2))
    return _style(fig)


# ---------- app ----------
st.set_page_config(page_title="Energy Dashboard", page_icon="⚡", layout="wide")
st.title("⚡ Energy Dashboard")

with st.sidebar:
    st.header("Filters")
    if st.button("🔄 Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    energy = load_energy()
    tariffs = load_tariffs()
    df = join_cost(energy, tariffs)

    min_d = df["start"].min().date()
    max_d = df["start"].max().date()
    default_start = max(min_d, max_d - timedelta(days=90))
    dr = st.date_input(
        "Date range",
        value=(default_start, max_d),
        min_value=min_d,
        max_value=max_d,
    )
    if isinstance(dr, tuple) and len(dr) == 2:
        start_d, end_d = dr
    else:
        start_d, end_d = default_start, max_d

    freq_label = st.radio("Aggregation", ["Daily", "Weekly", "Monthly"], horizontal=True)
    freq = {"Daily": "D", "Weekly": "W", "Monthly": "MS"}[freq_label]

    st.caption(f"Data: {min_d} → {max_d}  ·  {len(df):,} half-hour slots")

mask = (df["start"].dt.date >= start_d) & (df["start"].dt.date <= end_d)
dfw = df.loc[mask].copy()

if dfw.empty:
    st.warning("No data in the selected range.")
    st.stop()

daily_w = daily(dfw)
n_days = max((end_d - start_d).days + 1, 1)

total_kwh = dfw["kwh"].sum()
total_cost = dfw["cost_gbp"].sum()
avg_day = total_cost / n_days
base = baseload_kwh_per_day(dfw)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total kWh", f"{total_kwh:,.1f}")
c2.metric("Total cost", f"£{total_cost:,.2f}")
c3.metric("Avg £/day", f"£{avg_day:,.2f}")
c4.metric("Baseload", f"{base:.2f} kWh/day",
          help="Mean consumption between 01:00–04:30, scaled to a full day. The 'always on' draw.")

st.plotly_chart(chart_daily(daily_w, freq), use_container_width=True)

col_a, col_b = st.columns([1, 1])
with col_a:
    st.plotly_chart(chart_calendar_heatmap(daily_w), use_container_width=True)
with col_b:
    st.plotly_chart(chart_time_of_day(dfw), use_container_width=True)
