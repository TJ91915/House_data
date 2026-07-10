"""Motion page — reads motion-log events from Google Sheets."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import (
    C_ENERGY, C_STANDING, C_KWH, C_ROLLING, C_TEMP_MIN, C_TEMP_MEAN, C_TEMP_MAX,
    chart_year_over_year, freq_label, freq_selector, load_motion, style,
)

DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
# One colour per weekday — reuses the shared palette so the theme stays consistent.
DOW_COLOURS = [
    C_ENERGY, C_KWH, C_TEMP_MIN, C_TEMP_MEAN, C_TEMP_MAX, C_ROLLING, C_STANDING,
]


# ---------- charts ----------
def chart_hour_by_weekday(df: pd.DataFrame) -> go.Figure:
    grp = (
        df.groupby(["weekday", "hour"]).size()
        .rename("events").reset_index()
    )
    # Ensure every (weekday, hour) cell exists so lines are continuous.
    full = pd.MultiIndex.from_product([range(7), range(24)], names=["weekday", "hour"])
    grp = grp.set_index(["weekday", "hour"]).reindex(full, fill_value=0).reset_index()
    labels = [f"{h:02d}:00-{(h + 1) % 24:02d}:00" for h in range(24)]

    fig = go.Figure()
    for wd in range(7):
        row = grp[grp["weekday"] == wd].sort_values("hour")
        fig.add_scatter(
            x=labels, y=row["events"],
            name=DOW_LABELS[wd], mode="lines+markers",
            line=dict(color=DOW_COLOURS[wd], width=2),
            marker=dict(size=5),
            hovertemplate=f"{DOW_LABELS[wd]} %{{x}}<br>%{{y}} events<extra></extra>",
        )
    fig.update_layout(
        title="Motion events by hour — one line per day of week",
        yaxis=dict(title="Events", rangemode="tozero"),
        xaxis=dict(title="", tickangle=-45),
        legend=dict(orientation="h", y=-0.25),
        height=440,
        margin=dict(l=40, r=40, t=60, b=100),
    )
    return style(fig)


def chart_events_per_period(df: pd.DataFrame, freq: str) -> go.Figure:
    s = df.assign(date=pd.to_datetime(df["date"])).set_index("date")
    grp = s.resample(freq).size().rename("events").reset_index()
    label = freq_label(freq)
    fig = go.Figure(go.Bar(
        x=grp["date"], y=grp["events"],
        marker=dict(color=C_ENERGY),
        hovertemplate="%{x|%a %d %b %Y}<br>%{y:,} events<extra></extra>",
    ))
    fig.update_layout(
        title=f"{label} motion events  ·  {len(df):,} events over {len(grp):,} {label.lower()} buckets",
        yaxis=dict(title="Events", rangemode="tozero"),
        xaxis=dict(title=""),
        height=380,
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return style(fig)


# ---------- page ----------
st.title("🚶 Motion")

with st.sidebar:
    st.header("Motion filters")
    if st.button("🔄 Refresh data", key="motion_refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    df = load_motion()

    min_d = df["ts"].min().date()
    max_d = df["ts"].max().date()
    dr = st.date_input(
        "Date range",
        value=(min_d, max_d),  # default: all data
        min_value=min_d, max_value=max_d,
        key="motion_date_range",
    )
    start_d, end_d = dr if isinstance(dr, tuple) and len(dr) == 2 else (min_d, max_d)

    freq = freq_selector("motion")

    st.caption(f"Data: {min_d} → {max_d}  ·  {len(df):,} motion events")

mask = (df["ts"].dt.date >= start_d) & (df["ts"].dt.date <= end_d)
dfw = df.loc[mask].copy()

if dfw.empty:
    st.warning("No motion events in the selected range.")
    st.stop()

# KPIs
n_days = max((end_d - start_d).days + 1, 1)
hour_totals = dfw.groupby("hour").size()
weekday_totals = dfw.groupby("weekday").size()
busiest_hour = int(hour_totals.idxmax())
busiest_weekday = int(weekday_totals.idxmax())

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total events", f"{len(dfw):,}")
c2.metric("Avg events/day", f"{len(dfw) / n_days:,.1f}")
c3.metric("Busiest hour", f"{busiest_hour:02d}:00-{(busiest_hour + 1) % 24:02d}:00",
          help=f"{int(hour_totals.max()):,} events in this hour across the window")
c4.metric("Busiest weekday", DOW_LABELS[busiest_weekday],
          help=f"{int(weekday_totals.max()):,} events on {DOW_LABELS[busiest_weekday]}s")

st.plotly_chart(chart_hour_by_weekday(dfw), use_container_width=True)
st.plotly_chart(chart_events_per_period(dfw, freq), use_container_width=True)

# Year-over-year: events per bucket, one line per year. Resample fills
# event-free days with 0 so quiet days count as quiet, not missing.
daily_events = (
    dfw.set_index("ts").resample("D").size().rename("events").reset_index()
    .rename(columns={"ts": "date"})
)
st.plotly_chart(
    chart_year_over_year(daily_events, "events", freq, unit="events", value_fmt=",.0f"),
    use_container_width=True,
)
