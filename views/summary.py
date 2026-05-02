"""Summary page — homepage embed snapshot across all five datasets."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import (
    C_ENERGY, C_HOT_WATER, C_KWH, C_TEMP_MEAN, C_WATER,
    derive_dd_timeline, derive_water_tariff_history,
    join_cost, join_hot_water_paid, join_water_cost,
    load_energy, load_hot_water, load_hot_water_dd,
    load_motion, load_tariffs, load_temperature,
    load_water, load_water_tariffs,
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
water_raw = load_water()
water_tc = load_water_tariffs()
hot_water_raw = load_hot_water()
hot_water_dd = load_hot_water_dd()
energy = join_cost(energy_raw, tariffs).assign(d=lambda x: x["start"].dt.date)
water = join_water_cost(
    water_raw,
    derive_water_tariff_history(water_tc),
    derive_dd_timeline(water_tc),
)
hot_water = join_hot_water_paid(hot_water_raw, hot_water_dd)

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

# Water: latest day's L + cost, with deltas vs prior-7-day avg
today_w = water["date"].max().date()
today_w_row = water[water["date"].dt.date == today_w].iloc[0]
water_today = float(today_w_row["cons_l"])
water_today_cost = float(today_w_row["total_cost_gbp"])
prior_w_dates = pd.to_datetime([today_w - timedelta(days=i) for i in range(1, 8)])
prior_w = water[water["date"].isin(prior_w_dates)]
avg_water_l = float(prior_w["cons_l"].mean()) if not prior_w.empty else None
avg_water_cost = float(prior_w["total_cost_gbp"].mean()) if not prior_w.empty else None
water_delta = water_today - avg_water_l if avg_water_l is not None else None
water_cost_delta = water_today_cost - avg_water_cost if avg_water_cost is not None else None

# Hot water: latest day's kWh + cost, deltas vs prior-7-day avg
today_h = hot_water["date"].max().date()
today_h_row = hot_water[hot_water["date"].dt.date == today_h].iloc[0]
hot_water_today = float(today_h_row["kwh_used"])
hot_water_today_cost = float(today_h_row["total_cost_gbp"])
prior_h_dates = pd.to_datetime([today_h - timedelta(days=i) for i in range(1, 8)])
prior_h = hot_water[hot_water["date"].isin(prior_h_dates)]
avg_hot_water_kwh = float(prior_h["kwh_used"].mean()) if not prior_h.empty else None
avg_hot_water_cost = float(prior_h["total_cost_gbp"].mean()) if not prior_h.empty else None
hot_water_delta = hot_water_today - avg_hot_water_kwh if avg_hot_water_kwh is not None else None
hot_water_cost_delta = (
    hot_water_today_cost - avg_hot_water_cost if avg_hot_water_cost is not None else None
)

# Last reading across all five sources
last_updated = max(
    energy["start"].max(), temp["ts"].max(), motion["ts"].max(),
    water["date"].max(), hot_water["date"].max(),
)

# ---------- render ----------
st.title("🏠 Home")

# Top row — state of the house / today's consumption
r1c1, r1c2, r1c3, r1c4 = st.columns(4)
r1c1.metric(
    "Indoor temp",
    f"{latest_temp:.1f} °C",
    f"{temp_delta:+.1f} °C" if temp_delta is not None else None,
    delta_color="off",
    help=f"As of {latest_temp_ts:%H:%M, %a %d %b}. Δ vs same hour yesterday.",
)
r1c2.metric(
    f"Motion — {today_m:%d %b}",
    f"{motion_today:,}",
    f"{motion_delta:+.0f} vs 7d avg" if motion_delta is not None else None,
    delta_color="off",
)
r1c3.metric(
    f"Water — {today_w:%d %b}",
    f"{water_today:,.0f} L",
    f"{water_delta:+,.0f} vs 7d avg" if water_delta is not None else None,
    delta_color="inverse",
)
r1c4.metric(
    f"Hot Water — {today_h:%d %b}",
    f"{hot_water_today:,.1f} kWh",
    f"{hot_water_delta:+,.1f} vs 7d avg" if hot_water_delta is not None else None,
    delta_color="inverse",
)

# Bottom row — today's £ spend
r2c1, r2c2, r2c3, r2c4 = st.columns(4)
r2c1.metric(
    f"kWh — {today_e:%d %b}",
    f"{today_kwh:.2f}",
    f"{kwh_delta:+.2f} vs 7d avg" if kwh_delta is not None else None,
    delta_color="inverse",
)
r2c2.metric(
    f"Energy cost — {today_e:%d %b}",
    f"£{today_cost:.2f}",
    f"£{cost_delta:+.2f} vs 7d avg" if cost_delta is not None else None,
    delta_color="inverse",
)
r2c3.metric(
    f"Water cost — {today_w:%d %b}",
    f"£{water_today_cost:.2f}",
    f"£{water_cost_delta:+.2f} vs 7d avg" if water_cost_delta is not None else None,
    delta_color="inverse",
    help="Calculated daily cost: fresh + waste + standing − rebate.",
)
r2c4.metric(
    f"Hot Water cost — {today_h:%d %b}",
    f"£{hot_water_today_cost:.2f}",
    f"£{hot_water_cost_delta:+.2f} vs 7d avg" if hot_water_cost_delta is not None else None,
    delta_color="inverse",
    help="kWh cost + service charge per day.",
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
water_window = pd.to_datetime(window)
water_series = (
    water[water["date"].isin(water_window)]
    .set_index("date")["cons_l"]
    .reindex(water_window, fill_value=0)
)
hot_water_series = (
    hot_water[hot_water["date"].isin(water_window)]
    .set_index("date")["kwh_used"]
    .reindex(water_window, fill_value=0)
)

s1, s2, s3, s4, s5 = st.columns(5)
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
with s4:
    st.caption("14-day water (L)")
    st.plotly_chart(
        _sparkline(window, water_series.values, C_WATER, kind="bar"),
        use_container_width=True, config={"displayModeBar": False},
    )
with s5:
    st.caption("14-day hot water (kWh)")
    st.plotly_chart(
        _sparkline(window, hot_water_series.values, C_HOT_WATER, kind="bar"),
        use_container_width=True, config={"displayModeBar": False},
    )

st.caption(f"Last reading: {last_updated:%a %d %b %Y %H:%M}")
