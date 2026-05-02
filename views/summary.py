"""Summary page — homepage embed snapshot of all three datasets."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import (
    C_ENERGY, C_KWH, C_TEMP_MEAN,
    load_energy, load_motion, load_tariffs, load_temperature, join_cost,
)


def _sparkline(x, y, color: str, kind: str = "line") -> go.Figure:
    """Minimal axis-less sparkline for KPI strips."""
    fig = go.Figure()
    if kind == "bar":
        fig.add_bar(x=list(x), y=list(y), marker_color=color)
    else:
        fig.add_scatter(
            x=list(x), y=list(y), mode="lines",
            line=dict(color=color, width=2),
        )
    fig.update_layout(
        height=110,
        margin=dict(l=0, r=0, t=8, b=0),
        showlegend=False,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# ---------- load ----------
energy_raw = load_energy()
tariffs = load_tariffs()
temp = load_temperature()
motion = load_motion()
energy = join_cost(energy_raw, tariffs).assign(d=lambda x: x["start"].dt.date)

# ---------- compute KPIs ----------
# Indoor temp: latest reading, delta vs same hour yesterday
latest_t = temp.iloc[-1]
latest_temp = float(latest_t["temp_c"])
latest_temp_ts = latest_t["ts"]
y_same_hr = temp[
    (temp["date"] == latest_temp_ts.date() - timedelta(days=1))
    & (temp["hour"] == latest_temp_ts.hour)
]["temp_c"].mean()
temp_delta = latest_temp - y_same_hr if pd.notna(y_same_hr) else None

# Energy anchors on the latest *complete* day (48 half-hour slots) so the tile is
# meaningful even when the most recent date is partial (Octopus pulls catch up daily).
slots_per_day = energy.groupby("d").size()
complete_days = sorted(slots_per_day[slots_per_day >= 48].index)
today_e = complete_days[-1] if complete_days else energy["d"].max()
today_e_mask = energy["d"] == today_e
today_kwh = float(energy.loc[today_e_mask, "kwh"].sum())
today_cost = float(energy.loc[today_e_mask, "cost_gbp"].sum())

prior_e_dates = complete_days[-8:-1] if len(complete_days) >= 2 else []
prior_e = (
    energy[energy["d"].isin(prior_e_dates)]
    .groupby("d").agg(kwh=("kwh", "sum"), cost=("cost_gbp", "sum"))
)
avg_kwh = float(prior_e["kwh"].mean()) if not prior_e.empty else None
avg_cost = float(prior_e["cost"].mean()) if not prior_e.empty else None
kwh_delta = today_kwh - avg_kwh if avg_kwh is not None else None
cost_delta = today_cost - avg_cost if avg_cost is not None else None

# Motion: events today + delta vs prior-7-day avg
today_m = motion["date"].max()
motion_today = int((motion["date"] == today_m).sum())
prior_m_dates = [today_m - timedelta(days=i) for i in range(1, 8)]
prior_m = motion[motion["date"].isin(prior_m_dates)].groupby("date").size()
avg_motion = float(prior_m.mean()) if not prior_m.empty else None
motion_delta = motion_today - avg_motion if avg_motion is not None else None

# Baseload: mean overnight slot over the last 7 *complete* days, scaled to a full day
recent_e_dates = complete_days[-7:]
baseload_slot = energy_raw[
    energy_raw["date"].isin(recent_e_dates)
    & (energy_raw["hhmm"] >= "01:00")
    & (energy_raw["hhmm"] <= "04:30")
]["kwh"].mean()
baseload = float(baseload_slot * 48) if pd.notna(baseload_slot) else 0.0

# Last reading across all three sources
last_updated = max(energy["start"].max(), temp["ts"].max(), motion["ts"].max())

# ---------- render ----------
st.title("🏠 Home")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric(
    "Indoor temp",
    f"{latest_temp:.1f} °C",
    f"{temp_delta:+.1f} °C" if temp_delta is not None else None,
    delta_color="off",
    help=f"As of {latest_temp_ts:%H:%M, %a %d %b}. Δ vs same hour yesterday.",
)
c2.metric(
    f"kWh — {today_e:%d %b}",
    f"{today_kwh:.2f}",
    f"{kwh_delta:+.2f} vs 7d avg" if kwh_delta is not None else None,
    delta_color="inverse",
)
c3.metric(
    f"Cost — {today_e:%d %b}",
    f"£{today_cost:.2f}",
    f"{cost_delta:+.2f} vs 7d avg" if cost_delta is not None else None,
    delta_color="inverse",
)
c4.metric(
    f"Motion — {today_m:%d %b}",
    f"{motion_today:,}",
    f"{motion_delta:+.0f} vs 7d avg" if motion_delta is not None else None,
    delta_color="off",
)
c5.metric(
    "Baseload",
    f"{baseload:.2f} kWh/day",
    help="Mean overnight (01:00–04:30) draw scaled to a full day, last 7 days.",
)

# ---------- 14-day sparklines ----------
# Anchor on the most-recent reading across all three sources so sparklines feel "now",
# and partial-energy days will visibly show as gaps if the upstream feed is broken.
window_end = last_updated.date()
window = [window_end - timedelta(days=i) for i in range(13, -1, -1)]

temp_series = (
    temp[temp["date"].isin(window)]
    .groupby("date")["temp_c"].mean()
    .reindex(window)
)
kwh_series = (
    energy[energy["d"].isin(window)]
    .groupby("d")["kwh"].sum()
    .reindex(window, fill_value=0)
)
motion_series = (
    motion[motion["date"].isin(window)]
    .groupby("date").size()
    .reindex(window, fill_value=0)
)

s1, s2, s3 = st.columns(3)
with s1:
    st.caption("14-day temp (mean °C)")
    st.plotly_chart(
        _sparkline(window, temp_series.values, C_TEMP_MEAN),
        use_container_width=True, config={"displayModeBar": False},
    )
with s2:
    st.caption("14-day kWh")
    st.plotly_chart(
        _sparkline(window, kwh_series.values, C_KWH, kind="bar"),
        use_container_width=True, config={"displayModeBar": False},
    )
with s3:
    st.caption("14-day motion events")
    st.plotly_chart(
        _sparkline(window, motion_series.values, C_ENERGY),
        use_container_width=True, config={"displayModeBar": False},
    )

st.caption(f"Last reading: {last_updated:%a %d %b %Y %H:%M}")
