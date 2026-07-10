"""Hot Water page — daily kWh consumption + cost from district-heater data.

Mirrors the Water page's layout but unit-swaps: kWh + £ instead of L + £, and
uses the user-curated `Total kWh cost (p) per day` / `Total Service charge per
day` columns directly (no Python-side cost-join). Adds a running paid-vs-cost
balance chart driven by the `DD timeline` tab.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import (
    C_DEBT, C_GRID, C_HOT_WATER, C_KWH, C_ROLLING, C_STANDING, C_TEXT,
    HEAT_SCALE_HOT_WATER,
    build_daily_balance, chart_year_over_year, freq_label, freq_selector,
    join_hot_water_paid, load_eon_bills, load_hot_water, load_hot_water_dd, style,
)


def _aggregate(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Resample to chosen freq. Sums for kWh + £ columns, keeps `paid_per_day_gbp`
    as period-total under the alias `paid_gbp_period`."""
    if freq == "D":
        out = df.copy()
        out["paid_gbp_period"] = out["paid_per_day_gbp"]
        return out
    return (
        df.set_index("date")
        .resample(freq)
        .agg({
            "kwh_used": "sum",
            "kwh_cost_gbp": "sum",
            "service_gbp": "sum",
            "total_cost_gbp": "sum",
            "paid_per_day_gbp": "sum",
        })
        .reset_index()
        .rename(columns={"paid_per_day_gbp": "paid_gbp_period"})
    )


# ---------- charts ----------
def chart_volume(df_agg: pd.DataFrame, freq: str) -> go.Figure:
    label = freq_label(freq)
    fig = go.Figure()
    fig.add_bar(
        x=df_agg["date"], y=df_agg["kwh_used"], name="kWh",
        marker_color=C_HOT_WATER,
        hovertemplate="%{x|%d %b %Y}<br>%{y:,.1f} kWh<extra></extra>",
    )
    if freq == "D" and len(df_agg) >= 7:
        d = df_agg.assign(roll_7=df_agg["kwh_used"].rolling(7, min_periods=1).mean())
        fig.add_scatter(
            x=d["date"], y=d["roll_7"], name="7-day avg",
            mode="lines", line=dict(color=C_ROLLING, width=2, dash="dot"),
        )
    fig.update_layout(
        title=f"{label} hot water consumption (kWh)",
        yaxis=dict(title="kWh", rangemode="tozero"),
        xaxis=dict(title=""),
        legend=dict(orientation="h", y=-0.15),
        height=380,
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return style(fig)


def chart_cost(df_agg: pd.DataFrame, freq: str) -> go.Figure:
    label = freq_label(freq)
    fig = go.Figure()
    fig.add_bar(
        x=df_agg["date"], y=df_agg["kwh_cost_gbp"], name="kWh cost",
        marker_color=C_HOT_WATER,
        hovertemplate="%{x|%d %b %Y}<br>kWh: £%{y:.2f}<extra></extra>",
    )
    fig.add_bar(
        x=df_agg["date"], y=df_agg["service_gbp"], name="Service charge",
        marker_color=C_STANDING,
        hovertemplate="%{x|%d %b %Y}<br>Service: £%{y:.2f}<extra></extra>",
    )
    fig.add_scatter(
        x=df_agg["date"], y=df_agg["paid_gbp_period"], name="Paid (DD share)",
        mode="lines", line=dict(color=C_KWH, width=2, dash="dot"),
        hovertemplate="%{x|%d %b %Y}<br>Paid: £%{y:.2f}<extra></extra>",
    )
    fig.update_layout(
        title=f"{label} cost (£) — calculated vs actually paid",
        barmode="stack",
        yaxis=dict(title="£", rangemode="tozero"),
        xaxis=dict(title=""),
        legend=dict(orientation="h", y=-0.15),
        height=380,
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return style(fig)


def chart_running_balance(daily: pd.DataFrame, bills: pd.DataFrame) -> go.Figure:
    """Plot the real account balance anchored to E.on bill `new_balance` values.

    Convention follows E.on bills: positive = owing (red), negative = in credit
    (green/black). Bill dates marked with dots so it's obvious where the chart
    is fact (anchor) vs interpolation (between anchors).
    """
    d = daily.copy()
    # Balance line — break into segments above/below zero for two-tone colouring
    fig = go.Figure()
    fig.add_scatter(
        x=d["date"], y=d["balance_gbp"],
        mode="lines", line=dict(color=C_DEBT, width=2),
        name="Balance",
        hovertemplate="%{x|%d %b %Y}<br>Balance: £%{y:.2f}<extra></extra>",
    )
    # Credit-zone shading (when balance < 0) — overlay a second trace clipped to <= 0
    credit_y = d["balance_gbp"].where(d["balance_gbp"] <= 0)
    fig.add_scatter(
        x=d["date"], y=credit_y,
        mode="lines", line=dict(color=C_TEXT, width=2),
        name="In credit",
        hovertemplate="%{x|%d %b %Y}<br>Credit: £%{y:.2f}<extra></extra>",
    )
    # Bill anchors — one marker per actual statement
    anchors = d[d["is_bill_anchor"]]
    fig.add_scatter(
        x=anchors["date"], y=anchors["balance_gbp"],
        mode="markers",
        marker=dict(color=C_HOT_WATER, size=7, line=dict(color="white", width=1)),
        name="E.on bill",
        hovertemplate=(
            "%{x|%d %b %Y}<br>Bill balance: £%{y:.2f}"
            "<extra>statement</extra>"
        ),
    )
    fig.add_hline(y=0, line_dash="dash", line_color=C_GRID, line_width=1)
    final = d.iloc[-1]
    final_label = (
        f"in debit £{final['balance_gbp']:.2f}"
        if final["balance_gbp"] > 0 else
        f"in credit £{-final['balance_gbp']:.2f}"
    )
    n_bills = int(d["is_bill_anchor"].sum())
    fig.update_layout(
        title=(
            f"Account balance — anchored to {n_bills} E.on statements. "
            f"Red above £0 = owing · Black below £0 = in credit. "
            f"Latest: {final_label}"
        ),
        yaxis=dict(title="£"),
        xaxis=dict(title=""),
        height=380,
        margin=dict(l=40, r=40, t=60, b=40),
        showlegend=False,
    )
    return style(fig)


def chart_calendar_heatmap(df: pd.DataFrame) -> go.Figure:
    d = df.copy()
    d["dow"] = d["date"].dt.weekday
    d["week"] = d["date"] - pd.to_timedelta(d["dow"], unit="d")
    pivot = d.pivot_table(index="dow", columns="week", values="kwh_used", aggfunc="sum").reindex(range(7))
    dow_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    fig = go.Figure(go.Heatmap(
        z=pivot.values,
        x=[c.strftime("%Y-%m-%d") for c in pivot.columns],
        y=dow_labels,
        colorscale=HEAT_SCALE_HOT_WATER,
        colorbar=dict(title="kWh/day"),
        hovertemplate="Week of %{x}<br>%{y}<br>%{z:,.1f} kWh<extra></extra>",
    ))
    fig.update_layout(
        title="Daily kWh — calendar heatmap",
        height=320,
        margin=dict(l=40, r=40, t=60, b=40),
        yaxis=dict(autorange="reversed"),
    )
    return style(fig)


def chart_weekday_avg(df: pd.DataFrame) -> go.Figure:
    dow_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    grp = (
        df.groupby("weekday")["kwh_used"].mean()
        .reindex(range(7))
        .reset_index()
    )
    grp["label"] = grp["weekday"].map(lambda i: dow_labels[i])
    fig = go.Figure(go.Bar(
        x=grp["label"], y=grp["kwh_used"],
        marker=dict(color=C_HOT_WATER),
        hovertemplate="%{x}<br>%{y:,.1f} kWh<extra></extra>",
    ))
    fig.update_layout(
        title="Average kWh per day — by day of week",
        yaxis=dict(title="kWh", rangemode="tozero"),
        xaxis=dict(title=""),
        height=320,
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return style(fig)


# ---------- page ----------
st.title("🔥 Hot Water")

with st.sidebar:
    st.header("Hot Water filters")
    if st.button("🔄 Refresh data", key="hot_water_refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    raw = load_hot_water()
    dd = load_hot_water_dd()
    bills = load_eon_bills()
    df = join_hot_water_paid(raw, dd)

    min_d = df["date"].min().date()
    max_d = df["date"].max().date()
    dr = st.date_input(
        "Date range",
        value=(min_d, max_d),
        min_value=min_d, max_value=max_d,
        key="hot_water_date_range",
    )
    start_d, end_d = dr if isinstance(dr, tuple) and len(dr) == 2 else (min_d, max_d)

    freq = freq_selector("hot_water")

    st.caption(f"Data: {min_d} → {max_d}  ·  {len(df):,} daily readings")

mask = (df["date"].dt.date >= start_d) & (df["date"].dt.date <= end_d)
dfw = df.loc[mask].copy()

if dfw.empty:
    st.warning("No data in the selected range.")
    st.stop()

# ---------- KPIs ----------
n_days = len(dfw)
total_kwh = float(dfw["kwh_used"].sum())
total_cost = float(dfw["total_cost_gbp"].sum())
max_row = dfw.loc[dfw["kwh_used"].idxmax()]
latest_row = dfw.iloc[-1]
latest_bill = bills.iloc[-1] if not bills.empty else None

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Total kWh", f"{total_kwh:,.0f}",
          help=f"over {n_days} days")
c2.metric("Avg kWh/day", f"{total_kwh / n_days:,.1f}")
c3.metric("Total cost", f"£{total_cost:,.2f}")
c4.metric("Avg £/day", f"£{total_cost / n_days:.2f}")
if latest_bill is not None:
    bal = float(latest_bill["new_balance"])
    label = f"£{bal:.2f} owing" if bal > 0 else f"£{-bal:.2f} in credit"
    c5.metric("Account balance", label,
              help=f"From E.on statement {latest_bill['doc_date']:%d %b %Y}. "
                   "Authoritative — taken straight from the bill.")
else:
    c5.metric("Account balance", "—", help="No E.on bills parsed yet.")
c6.metric("Latest day", f"{latest_row['kwh_used']:,.1f} kWh · £{latest_row['total_cost_gbp']:.2f}",
          help=f"on {latest_row['date']:%a %d %b %Y}")

df_agg = _aggregate(dfw, freq)
st.plotly_chart(chart_volume(df_agg, freq), use_container_width=True)
st.plotly_chart(
    chart_year_over_year(dfw, "kwh_used", freq),
    use_container_width=True,
)
st.plotly_chart(chart_cost(df_agg, freq), use_container_width=True)

# Running balance uses the full daily history (not the aggregated frame) and
# the bill anchors. Filter to the selected date range for visual consistency.
daily_bal = build_daily_balance(dfw, bills)
st.plotly_chart(chart_running_balance(daily_bal, bills), use_container_width=True)

col_a, col_b = st.columns([1, 1])
with col_a:
    st.plotly_chart(chart_calendar_heatmap(dfw), use_container_width=True)
with col_b:
    st.plotly_chart(chart_weekday_avg(dfw), use_container_width=True)

# ---------- per-day breakdown table ----------
st.subheader("Daily breakdown (most recent 30 days)")
recent = dfw.sort_values("date", ascending=False).head(30).copy()
recent["Date"] = recent["date"].dt.strftime("%a %d %b %Y")
display = recent[[
    "Date", "kwh_used", "unit_rate_p_kwh", "kwh_cost_gbp",
    "service_p_day", "service_gbp", "total_cost_gbp",
    "monthly_dd", "paid_per_day_gbp",
]].rename(columns={
    "kwh_used": "kWh",
    "unit_rate_p_kwh": "Rate p/kWh",
    "kwh_cost_gbp": "kWh £",
    "service_p_day": "Service p/d",
    "service_gbp": "Service £",
    "total_cost_gbp": "Total £",
    "monthly_dd": "Monthly DD £",
    "paid_per_day_gbp": "Paid £/d",
})
st.dataframe(
    display,
    hide_index=True,
    use_container_width=True,
    column_config={
        "kWh": st.column_config.NumberColumn(format="%.2f"),
        "Rate p/kWh": st.column_config.NumberColumn(format="%.3fp"),
        "kWh £": st.column_config.NumberColumn(format="£%.3f"),
        "Service p/d": st.column_config.NumberColumn(format="%.3fp"),
        "Service £": st.column_config.NumberColumn(format="£%.3f"),
        "Total £": st.column_config.NumberColumn(format="£%.3f"),
        "Monthly DD £": st.column_config.NumberColumn(format="£%.0f"),
        "Paid £/d": st.column_config.NumberColumn(format="£%.3f"),
    },
)
