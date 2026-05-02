"""Water page — daily consumption from Google Sheets."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import (
    C_ROLLING, C_WATER, HEAT_SCALE_WATER,
    load_water, style,
)


# ---------- charts ----------
def chart_daily(df: pd.DataFrame) -> go.Figure:
    """Daily L bar chart with 7-day rolling-mean overlay."""
    d = df.assign(roll_7=df["cons_l"].rolling(7, min_periods=1).mean())
    fig = go.Figure()
    fig.add_bar(
        x=d["date"], y=d["cons_l"], name="Daily L",
        marker_color=C_WATER,
        hovertemplate="%{x|%a %d %b %Y}<br>%{y:,.0f} L<extra></extra>",
    )
    fig.add_scatter(
        x=d["date"], y=d["roll_7"], name="7-day avg",
        mode="lines", line=dict(color=C_ROLLING, width=2, dash="dot"),
    )
    fig.update_layout(
        title="Daily water consumption (L)",
        yaxis=dict(title="Litres", rangemode="tozero"),
        xaxis=dict(title=""),
        legend=dict(orientation="h", y=-0.15),
        height=400,
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return style(fig)


def chart_calendar_heatmap(df: pd.DataFrame) -> go.Figure:
    d = df.copy()
    d["dow"] = d["date"].dt.weekday
    d["week"] = d["date"] - pd.to_timedelta(d["dow"], unit="d")
    pivot = d.pivot_table(index="dow", columns="week", values="cons_l", aggfunc="sum").reindex(range(7))
    dow_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    fig = go.Figure(go.Heatmap(
        z=pivot.values,
        x=[c.strftime("%Y-%m-%d") for c in pivot.columns],
        y=dow_labels,
        colorscale=HEAT_SCALE_WATER,
        colorbar=dict(title="L/day"),
        hovertemplate="Week of %{x}<br>%{y}<br>%{z:,.0f} L<extra></extra>",
    ))
    fig.update_layout(
        title="Daily L — calendar heatmap",
        height=320,
        margin=dict(l=40, r=40, t=60, b=40),
        yaxis=dict(autorange="reversed"),
    )
    return style(fig)


def chart_monthly(df: pd.DataFrame) -> go.Figure:
    """Monthly total L. Useful given the 2+ year history."""
    monthly = df.set_index("date").resample("MS")["cons_l"].sum().reset_index()
    fig = go.Figure(go.Bar(
        x=monthly["date"], y=monthly["cons_l"],
        marker=dict(color=C_WATER),
        hovertemplate="%{x|%b %Y}<br>%{y:,.0f} L<extra></extra>",
    ))
    fig.update_layout(
        title="Monthly total (L)",
        yaxis=dict(title="Litres", rangemode="tozero"),
        xaxis=dict(title=""),
        height=340,
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return style(fig)


def chart_weekday_avg(df: pd.DataFrame) -> go.Figure:
    dow_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    grp = (
        df.groupby("weekday")["cons_l"].mean()
        .reindex(range(7))
        .reset_index()
    )
    grp["label"] = grp["weekday"].map(lambda i: dow_labels[i])
    fig = go.Figure(go.Bar(
        x=grp["label"], y=grp["cons_l"],
        marker=dict(color=C_WATER),
        hovertemplate="%{x}<br>%{y:,.0f} L<extra></extra>",
    ))
    fig.update_layout(
        title="Average L per day — by day of week",
        yaxis=dict(title="Litres", rangemode="tozero"),
        xaxis=dict(title=""),
        height=340,
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return style(fig)


# ---------- page ----------
st.title("💧 Water")

with st.sidebar:
    st.header("Water filters")
    if st.button("🔄 Refresh data", key="water_refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    df = load_water()

    min_d = df["date"].min().date()
    max_d = df["date"].max().date()
    dr = st.date_input(
        "Date range",
        value=(min_d, max_d),
        min_value=min_d, max_value=max_d,
        key="water_date_range",
    )
    start_d, end_d = dr if isinstance(dr, tuple) and len(dr) == 2 else (min_d, max_d)

    st.caption(f"Data: {min_d} → {max_d}  ·  {len(df):,} daily readings")

mask = (df["date"].dt.date >= start_d) & (df["date"].dt.date <= end_d)
dfw = df.loc[mask].copy()

if dfw.empty:
    st.warning("No data in the selected range.")
    st.stop()

# ---------- KPIs ----------
total_l = float(dfw["cons_l"].sum())
n_days = len(dfw)
avg_l = total_l / n_days if n_days else 0.0
max_row = dfw.loc[dfw["cons_l"].idxmax()]
latest_row = dfw.iloc[-1]

# 4 tiles for now. When a per-m³ tariff is wired in, expand to 5: add a Cost tile.
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total", f"{total_l:,.0f} L",
          help=f"{total_l / 1000:,.2f} m³ over {n_days} days")
c2.metric("Avg per day", f"{avg_l:,.0f} L")
c3.metric("Max day", f"{max_row['cons_l']:,.0f} L",
          help=f"on {max_row['date']:%a %d %b %Y}")
c4.metric("Latest", f"{latest_row['cons_l']:,.0f} L",
          help=f"on {latest_row['date']:%a %d %b %Y}")

st.plotly_chart(chart_daily(dfw), use_container_width=True)

col_a, col_b = st.columns([1, 1])
with col_a:
    st.plotly_chart(chart_calendar_heatmap(dfw), use_container_width=True)
with col_b:
    st.plotly_chart(chart_monthly(dfw), use_container_width=True)

st.plotly_chart(chart_weekday_avg(dfw), use_container_width=True)
