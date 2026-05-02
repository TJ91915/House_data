"""Energy page — reads half-hourly consumption + tariffs from Google Sheets."""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from lib import (
    C_ENERGY, C_STANDING, C_KWH, C_ROLLING, HEAT_SCALE,
    style, load_energy, load_tariffs, join_cost,
)


# ---------- page-specific helpers ----------
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
    return df_daily.set_index("date").resample(freq).sum(numeric_only=True).reset_index()


def baseload_kwh_per_day(df: pd.DataFrame) -> float:
    mask = (df["hhmm"] >= "01:00") & (df["hhmm"] <= "04:30")
    slot_mean = df.loc[mask, "kwh"].mean()
    return float(slot_mean * 48) if pd.notna(slot_mean) else 0.0


# ---------- charts ----------
def chart_daily(df_daily: pd.DataFrame, freq: str) -> go.Figure:
    from lib import freq_label as _freq_label
    d = resample(df_daily, freq)
    label = _freq_label(freq)
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
    return style(fig)


def chart_calendar_heatmap(df_daily: pd.DataFrame) -> go.Figure:
    d = df_daily.copy()
    d["dow"] = d["date"].dt.weekday
    d["week"] = d["date"] - pd.to_timedelta(d["dow"], unit="d")
    pivot = d.pivot_table(index="dow", columns="week", values="kwh", aggfunc="sum").reindex(range(7))
    dow_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    fig = go.Figure(go.Heatmap(
        z=pivot.values,
        x=[c.strftime("%Y-%m-%d") for c in pivot.columns],
        y=dow_labels,
        colorscale=HEAT_SCALE,
        colorbar=dict(title="kWh/day"),
        hovertemplate="Week of %{x}<br>%{y}<br>%{z:.2f} kWh<extra></extra>",
    ))
    fig.update_layout(
        title="Daily kWh — calendar heatmap",
        height=320,
        margin=dict(l=40, r=40, t=60, b=40),
        yaxis=dict(autorange="reversed"),
    )
    return style(fig)


def chart_time_of_day(df: pd.DataFrame) -> go.Figure:
    d = df.copy()
    d["is_weekend"] = d["weekday"] >= 5
    agg = (
        d.groupby(["hhmm", "is_weekend"])["kwh"]
        .mean().reset_index().rename(columns={"kwh": "avg_kwh"})
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
    return style(fig)


def chart_weekday_avg(df: pd.DataFrame) -> go.Figure:
    dow_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    # Sum kWh per calendar date first, then average across dates sharing a weekday
    per_day = df.groupby(["date", "weekday"])["kwh"].sum().reset_index()
    grp = (
        per_day.groupby("weekday")["kwh"].mean()
        .reindex(range(7))
        .reset_index()
    )
    grp["label"] = grp["weekday"].map(lambda i: dow_labels[i])
    fig = go.Figure(go.Bar(
        x=grp["label"], y=grp["kwh"],
        marker=dict(color=C_KWH),
        hovertemplate="%{x}<br>%{y:,.2f} kWh<extra></extra>",
    ))
    fig.update_layout(
        title="Average kWh per day — by day of week",
        yaxis=dict(title="kWh", rangemode="tozero"),
        xaxis=dict(title=""),
        height=340,
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return style(fig)


def chart_hour_avg(df: pd.DataFrame) -> go.Figure:
    # Sum each hour's kWh per date (2 half-hour slots collapse to one hour), then
    # average across dates so each bar is the mean kWh an hour uses on a typical day.
    d = df.assign(hour=df["start"].dt.hour)
    per_day_hour = d.groupby(["date", "hour"])["kwh"].sum().reset_index()
    grp = (
        per_day_hour.groupby("hour")["kwh"].mean()
        .reindex(range(24))
        .reset_index()
    )
    grp["label"] = grp["hour"].map(lambda h: f"{h:02d}:00-{(h + 1) % 24:02d}:00")
    fig = go.Figure(go.Bar(
        x=grp["label"], y=grp["kwh"],
        marker=dict(color=C_KWH),
        hovertemplate="%{x}<br>%{y:,.2f} kWh<extra></extra>",
    ))
    fig.update_layout(
        title="Average kWh per hour — by hour of day",
        yaxis=dict(title="kWh", rangemode="tozero"),
        xaxis=dict(title="", tickangle=-45),
        height=340,
        margin=dict(l=40, r=40, t=60, b=80),
    )
    return style(fig)


# ---------- page ----------
st.title("⚡ Energy")

with st.sidebar:
    st.header("Energy filters")
    if st.button("🔄 Refresh data", key="energy_refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    energy = load_energy()
    tariffs = load_tariffs()
    df = join_cost(energy, tariffs)

    min_d = df["start"].min().date()
    max_d = df["start"].max().date()
    dr = st.date_input(
        "Date range",
        value=(min_d, max_d),  # default: all data
        min_value=min_d, max_value=max_d,
        key="energy_date_range",
    )
    start_d, end_d = dr if isinstance(dr, tuple) and len(dr) == 2 else (min_d, max_d)

    from lib import freq_selector
    freq = freq_selector("energy")

    st.caption(f"Data: {min_d} → {max_d}  ·  {len(df):,} half-hour slots")

mask = (df["start"].dt.date >= start_d) & (df["start"].dt.date <= end_d)
dfw = df.loc[mask].copy()

if dfw.empty:
    st.warning("No data in the selected range.")
    st.stop()

daily_w = daily(dfw)
n_days = max((end_d - start_d).days + 1, 1)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total kWh", f"{dfw['kwh'].sum():,.1f}")
c2.metric("Total cost", f"£{dfw['cost_gbp'].sum():,.2f}")
c3.metric("Avg £/day", f"£{dfw['cost_gbp'].sum() / n_days:,.2f}")
c4.metric("Baseload", f"{baseload_kwh_per_day(dfw):.2f} kWh/day",
          help="Mean consumption between 01:00–04:30, scaled to a full day. The 'always on' draw.")

st.plotly_chart(chart_daily(daily_w, freq), use_container_width=True)

col_a, col_b = st.columns([1, 1])
with col_a:
    st.plotly_chart(chart_calendar_heatmap(daily_w), use_container_width=True)
with col_b:
    st.plotly_chart(chart_time_of_day(dfw), use_container_width=True)

col_c, col_d = st.columns([1, 1])
with col_c:
    st.plotly_chart(chart_weekday_avg(dfw), use_container_width=True)
with col_d:
    st.plotly_chart(chart_hour_avg(dfw), use_container_width=True)
