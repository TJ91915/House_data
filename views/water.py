"""Water page — daily consumption + cost from Google Sheets."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import (
    C_DEBT, C_GRID, C_KWH, C_ROLLING, C_STANDING, C_TEXT, C_WATER, HEAT_SCALE_WATER,
    chart_year_over_year, derive_dd_timeline, derive_water_tariff_history,
    freq_label, freq_selector,
    join_water_cost, load_water, load_water_tariffs, style,
)


def _aggregate(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Resample the costed water dataframe to the chosen freq.

    All money/volume columns sum (period totals). `paid_per_day_gbp` is
    aliased to `paid_gbp_period` so charts can read one consistent name
    regardless of freq.
    """
    if freq == "D":
        out = df.copy()
        out["paid_gbp_period"] = out["paid_per_day_gbp"]
        return out
    return (
        df.set_index("date")
        .resample(freq)
        .agg({
            "cons_l": "sum",
            "cons_m3": "sum",
            "fw_subtotal_gbp": "sum",
            "ww_subtotal_gbp": "sum",
            "total_cost_gbp": "sum",
            "paid_per_day_gbp": "sum",
        })
        .reset_index()
        .rename(columns={"paid_per_day_gbp": "paid_gbp_period"})
    )


# ---------- charts ----------
def chart_volume(df_agg: pd.DataFrame, freq: str) -> go.Figure:
    """Volume bar chart at the chosen freq. 7-day rolling overlay only on Daily."""
    label = freq_label(freq)
    fig = go.Figure()
    fig.add_bar(
        x=df_agg["date"], y=df_agg["cons_l"], name="Litres",
        marker_color=C_WATER,
        hovertemplate="%{x|%d %b %Y}<br>%{y:,.0f} L<extra></extra>",
    )
    if freq == "D" and len(df_agg) >= 7:
        d = df_agg.assign(roll_7=df_agg["cons_l"].rolling(7, min_periods=1).mean())
        fig.add_scatter(
            x=d["date"], y=d["roll_7"], name="7-day avg",
            mode="lines", line=dict(color=C_ROLLING, width=2, dash="dot"),
        )
    fig.update_layout(
        title=f"{label} water consumption (L)",
        yaxis=dict(title="Litres", rangemode="tozero"),
        xaxis=dict(title=""),
        legend=dict(orientation="h", y=-0.15),
        height=380,
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return style(fig)


def chart_cost(df_agg: pd.DataFrame, freq: str) -> go.Figure:
    """Stacked £ chart at the chosen freq: FW + WW subtotals, with paid total overlaid."""
    label = freq_label(freq)
    fig = go.Figure()
    fig.add_bar(
        x=df_agg["date"], y=df_agg["fw_subtotal_gbp"], name="Fresh water",
        marker_color=C_WATER,
        hovertemplate="%{x|%d %b %Y}<br>FW: £%{y:.2f}<extra></extra>",
    )
    fig.add_bar(
        x=df_agg["date"], y=df_agg["ww_subtotal_gbp"], name="Waste water (net rebate)",
        marker_color=C_STANDING,
        hovertemplate="%{x|%d %b %Y}<br>WW: £%{y:.2f}<extra></extra>",
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


def chart_running_balance(df_agg: pd.DataFrame, freq: str) -> go.Figure:
    """Cumulative paid − cost balance, end-of-period. Black = paid up, red = under-paid."""
    label = freq_label(freq)
    d = df_agg.copy()
    d["period_net"] = d["paid_gbp_period"] - d["total_cost_gbp"]
    d["balance"] = d["period_net"].cumsum()
    colors = [C_TEXT if v >= 0 else C_DEBT for v in d["balance"]]
    fig = go.Figure(go.Bar(
        x=d["date"], y=d["balance"],
        marker_color=colors,
        hovertemplate=(
            "%{x|%d %b %Y}<br>Balance: £%{y:.2f}<br>"
            "Net this period: £%{customdata:+.2f}<extra></extra>"
        ),
        customdata=d["period_net"],
    ))
    fig.add_hline(y=0, line_dash="dash", line_color=C_GRID, line_width=1)
    fig.update_layout(
        title=f"{label} running balance — cumulative (paid − cost). Black = paid up · Red = under-paid",
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
        height=320,
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

    raw = load_water()
    tc = load_water_tariffs()
    history = derive_water_tariff_history(tc)
    dd_timeline = derive_dd_timeline(tc)
    df = join_water_cost(raw, history, dd_timeline)

    min_d = df["date"].min().date()
    max_d = df["date"].max().date()
    dr = st.date_input(
        "Date range",
        value=(min_d, max_d),
        min_value=min_d, max_value=max_d,
        key="water_date_range",
    )
    start_d, end_d = dr if isinstance(dr, tuple) and len(dr) == 2 else (min_d, max_d)

    freq = freq_selector("water")

    st.caption(f"Data: {min_d} → {max_d}  ·  {len(df):,} daily readings")

mask = (df["date"].dt.date >= start_d) & (df["date"].dt.date <= end_d)
dfw = df.loc[mask].copy()

if dfw.empty:
    st.warning("No data in the selected range.")
    st.stop()

# ---------- KPIs ----------
n_days = len(dfw)
total_l = float(dfw["cons_l"].sum())
total_cost = float(dfw["total_cost_gbp"].sum())
total_paid = float(dfw["paid_per_day_gbp"].sum())
max_row = dfw.loc[dfw["cons_l"].idxmax()]
latest_row = dfw.iloc[-1]

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Total", f"{total_l:,.0f} L",
          help=f"{total_l / 1000:,.2f} m³ over {n_days} days")
c2.metric("Avg L/day", f"{total_l / n_days:,.0f} L")
c3.metric("Total cost", f"£{total_cost:,.2f}",
          help="Calculated cost: fresh + waste + standing − rebate, all at daily resolution.")
c4.metric("Avg £/day", f"£{total_cost / n_days:.2f}")
c5.metric("Paid (DD)", f"£{total_paid:,.2f}",
          help=f"Annualised daily share of monthly DD over the {n_days} day window. "
               f"Diff vs Total cost = the credit/debt building up on your account.")
c6.metric("Latest day", f"{latest_row['cons_l']:,.0f} L · £{latest_row['total_cost_gbp']:.2f}",
          help=f"on {latest_row['date']:%a %d %b %Y}")

df_agg = _aggregate(dfw, freq)
st.plotly_chart(chart_volume(df_agg, freq), use_container_width=True)
st.plotly_chart(
    chart_year_over_year(dfw, "cons_l", freq, unit="L", value_fmt=",.0f"),
    use_container_width=True,
)
st.plotly_chart(chart_cost(df_agg, freq), use_container_width=True)
st.plotly_chart(chart_running_balance(df_agg, freq), use_container_width=True)

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
    "Date", "cons_m3", "fw_rate", "fw_standing_per_day", "fw_subtotal_gbp",
    "ww_rate", "ww_standing_per_day", "rebate_per_day", "ww_subtotal_gbp",
    "total_cost_gbp", "paid_per_day_gbp",
]].rename(columns={
    "cons_m3": "m³",
    "fw_rate": "FW £/m³",
    "fw_standing_per_day": "FW stand £/d",
    "fw_subtotal_gbp": "FW £",
    "ww_rate": "WW £/m³",
    "ww_standing_per_day": "WW stand £/d",
    "rebate_per_day": "Rebate £/d",
    "ww_subtotal_gbp": "WW £",
    "total_cost_gbp": "Total £",
    "paid_per_day_gbp": "Paid £/d",
})
st.dataframe(
    display,
    hide_index=True,
    use_container_width=True,
    column_config={
        "m³": st.column_config.NumberColumn(format="%.3f"),
        "FW £/m³": st.column_config.NumberColumn(format="£%.4f"),
        "FW stand £/d": st.column_config.NumberColumn(format="£%.4f"),
        "FW £": st.column_config.NumberColumn(format="£%.3f"),
        "WW £/m³": st.column_config.NumberColumn(format="£%.4f"),
        "WW stand £/d": st.column_config.NumberColumn(format="£%.4f"),
        "Rebate £/d": st.column_config.NumberColumn(format="£%.4f"),
        "WW £": st.column_config.NumberColumn(format="£%.3f"),
        "Total £": st.column_config.NumberColumn(format="£%.3f"),
        "Paid £/d": st.column_config.NumberColumn(format="£%.3f"),
    },
)
