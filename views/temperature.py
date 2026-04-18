"""Temperature page — reads Hue sensor data from Google Sheets."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import (
    C_TEMP_MIN, C_TEMP_MEAN, C_TEMP_MAX, C_TEMP_RIBBON, HEAT_SCALE_TEMP,
    style, load_temperature,
)


def daily_stats(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("date").agg(
        min_c=("temp_c", "min"),
        mean_c=("temp_c", "mean"),
        max_c=("temp_c", "max"),
    ).reset_index()
    g["date"] = pd.to_datetime(g["date"])
    return g


# ---------- charts ----------
def chart_daily_ribbon(d: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    # Max line (drawn first to anchor the fill)
    fig.add_scatter(
        x=d["date"], y=d["max_c"], name="Max",
        mode="lines", line=dict(color=C_TEMP_MAX, width=1.5),
    )
    # Min line — fill the gap between max and min
    fig.add_scatter(
        x=d["date"], y=d["min_c"], name="Min",
        mode="lines", line=dict(color=C_TEMP_MIN, width=1.5),
        fill="tonexty", fillcolor=C_TEMP_RIBBON,
    )
    # Mean on top
    fig.add_scatter(
        x=d["date"], y=d["mean_c"], name="Mean",
        mode="lines", line=dict(color=C_TEMP_MEAN, width=2.5),
    )
    fig.update_layout(
        title="Daily temperature — min / mean / max (°C)",
        yaxis=dict(title="°C"),
        xaxis=dict(title=""),
        legend=dict(orientation="h", y=-0.15),
        height=400,
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return style(fig)


def chart_hour_heatmap(df: pd.DataFrame) -> go.Figure:
    grp = df.groupby(["weekday", "hour"])["temp_c"].mean().reset_index()
    pivot = grp.pivot(index="weekday", columns="hour", values="temp_c").reindex(range(7))
    dow_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    fig = go.Figure(go.Heatmap(
        z=pivot.values,
        x=[f"{h:02d}" for h in pivot.columns],
        y=dow_labels,
        colorscale=HEAT_SCALE_TEMP,
        colorbar=dict(title="°C"),
        hovertemplate="%{y} %{x}:00<br>%{z:.2f} °C<extra></extra>",
    ))
    fig.update_layout(
        title="Average °C by hour × day of week",
        height=340,
        margin=dict(l=40, r=40, t=60, b=40),
        yaxis=dict(autorange="reversed"),
    )
    return style(fig)


def chart_raw(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Scatter(
        x=df["ts"], y=df["temp_c"], mode="lines",
        line=dict(color=C_TEMP_MEAN, width=1),
        hovertemplate="%{x|%d %b %Y %H:%M}<br>%{y:.2f} °C<extra></extra>",
    ))
    fig.update_layout(
        title=f"Every reading ({len(df):,} points)",
        yaxis=dict(title="°C"),
        xaxis=dict(title=""),
        height=400,
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return style(fig)


# ---------- page ----------
st.title("🌡️ Temperature")

with st.sidebar:
    st.header("Temperature filters")
    if st.button("🔄 Refresh data", key="temp_refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    df = load_temperature()

    min_d = df["ts"].min().date()
    max_d = df["ts"].max().date()
    dr = st.date_input(
        "Date range",
        value=(min_d, max_d),  # default: all data
        min_value=min_d, max_value=max_d,
        key="temp_date_range",
    )
    start_d, end_d = dr if isinstance(dr, tuple) and len(dr) == 2 else (min_d, max_d)

    st.caption(f"Data: {min_d} → {max_d}  ·  {len(df):,} readings")

mask = (df["ts"].dt.date >= start_d) & (df["ts"].dt.date <= end_d)
dfw = df.loc[mask].copy()

if dfw.empty:
    st.warning("No data in the selected range.")
    st.stop()

# KPIs — based on the selected window
latest = dfw.iloc[-1]
latest_date = dfw["date"].max()
today_df = dfw[dfw["date"] == latest_date]
last_7_cut = dfw["ts"].max() - timedelta(days=7)
avg_7d = dfw.loc[dfw["ts"] >= last_7_cut, "temp_c"].mean()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Latest", f"{latest['temp_c']:.1f} °C",
          help=f"as of {latest['ts']:%d %b %Y %H:%M}")
c2.metric(f"{latest_date:%d %b} min", f"{today_df['temp_c'].min():.1f} °C")
c3.metric(f"{latest_date:%d %b} max", f"{today_df['temp_c'].max():.1f} °C")
c4.metric("7-day avg", f"{avg_7d:.1f} °C")

# Charts
d_daily = daily_stats(dfw)
st.plotly_chart(chart_daily_ribbon(d_daily), use_container_width=True)

col_a, col_b = st.columns([1, 1])
with col_a:
    st.plotly_chart(chart_hour_heatmap(dfw), use_container_width=True)
with col_b:
    st.plotly_chart(chart_raw(dfw), use_container_width=True)
