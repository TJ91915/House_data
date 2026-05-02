"""Shared helpers for the multi-page House dashboard: auth, palette, chart styling, loaders."""
from __future__ import annotations

import re
from pathlib import Path

import gspread
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from google.oauth2.service_account import Credentials

CACHE_TTL = 7200  # 2 hours

# ---------- shared aggregation control ----------
# Shared by Energy / Temperature / Motion / Water pages so the radio looks identical.
FREQ_OPTIONS = ["Daily", "Weekly", "Monthly", "Yearly"]
FREQ_MAP = {"Daily": "D", "Weekly": "W", "Monthly": "MS", "Yearly": "YS"}


def freq_selector(key: str, default: str = "Daily") -> str:
    """Render a horizontal radio in the current container; return a pandas resample alias."""
    label = st.radio(
        "Aggregation",
        FREQ_OPTIONS,
        index=FREQ_OPTIONS.index(default),
        horizontal=True,
        key=f"{key}_freq",
    )
    return FREQ_MAP[label]


def freq_label(freq_str: str) -> str:
    """Inverse of freq_selector: 'D' -> 'Daily', 'W' -> 'Weekly', etc. For chart titles."""
    inv = {v: k for k, v in FREQ_MAP.items()}
    return inv.get(freq_str, freq_str)

# Sheet IDs
SHEET_ID_ENERGY = "1stKNr_MzA3fJL3kKSofMqxK4Nu66XbVtqsLzyosKqpQ"
SHEET_ID_TEMP   = "1ZOiXI_23xaTC7QAT6Z_l7v6H9KefbzTqM0UI5c7bDB0"
SHEET_ID_MOTION = "1rL54qg6g1eOxGZTWWkflqRFpE7QbFF11TUXyUhh6ov4"
SHEET_ID_WATER  = "1yoHfWhVb-g5blWnULsslQv1enkup48pRzbpRWX26ixo"
SHEET_ID_HOT_WATER = "1I3RQrsu7W9Bva_xBJh_L8i5eBunKH64zMhDqTQbJenc"

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
C_HOT_WATER = "#C28B6E"   # warm copper (hot water — district heating)
C_DEBT      = "#B85450"   # muted red — for under-paid / debt readings

HEAT_SCALE       = [[0, "#F3EADB"], [0.5, "#D49A6A"], [1, "#A84F2C"]]
HEAT_SCALE_TEMP  = [[0, "#7E9FBD"], [0.5, "#F0E6D6"], [1, "#C07855"]]  # cool→warm
HEAT_SCALE_WATER = [[0, "#F3EADB"], [0.5, "#9BB8CC"], [1, "#3B6884"]]  # cream→deep slate
HEAT_SCALE_HOT_WATER = [[0, "#F3EADB"], [0.5, "#D4A788"], [1, "#9C5638"]]  # cream→deep copper


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


@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading water tariffs…")
def load_water_tariffs() -> pd.DataFrame:
    """Read the `Tariff costs` tab. One row per bill or DD notice."""
    ws = client().open_by_key(SHEET_ID_WATER).worksheet("Tariff costs")
    rows = ws.get_all_values()
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df["doc_date"] = pd.to_datetime(df["Document Date"], errors="coerce")
    df["period_from"] = pd.to_datetime(df["Period From"], errors="coerce")
    df["period_to"] = pd.to_datetime(df["Period To"], errors="coerce")
    for col, alias in [
        ("Volume (m³)", "volume_m3"),
        ("Meter Read Start", "meter_start"),
        ("Meter Read End", "meter_end"),
        ("Fresh Water Rate (£/m³)", "fw_rate"),
        ("Fresh Water Standing (£)", "fw_standing"),
        ("Waste Water Rate (£/m³)", "ww_rate"),
        ("Waste Water Standing (£)", "ww_standing"),
        ("Drainage Rebate (£)", "rebate"),
        ("Fresh Water Charge (£)", "fw_charge"),
        ("Waste Water Charge (£)", "ww_charge"),
        ("Monthly DD (£)", "monthly_dd"),
        ("Total Charge (£)", "total_charge"),
    ]:
        df[alias] = pd.to_numeric(df[col], errors="coerce")
    df["notes"] = df.get("Notes", "")
    df["type"] = df["Type"]
    return df


def derive_water_tariff_history(tc: pd.DataFrame) -> pd.DataFrame:
    """Build a rate-effective-from table from the Tariff costs rows.

    Strategy:
      • For each tariff year (Apr-Mar), pick the longest single-rate Usage Bill
        and derive £/day standing charges from its period totals.
      • Add a pre-2023-04-01 row from any 2022/23-rates bill.
      • For tariff years where only split bills exist (typically the most-recent
        year), record the rates from the split-bill notes and fall back to the
        prior year's £/day standing charges.
    """
    bills = tc[tc["type"] == "Usage Bill"].dropna(subset=["period_from", "period_to"]).copy()
    bills["period_days"] = (bills["period_to"] - bills["period_from"]).dt.days + 1
    bills["is_single_rate"] = ~bills["notes"].fillna("").str.contains("Split-rate", regex=False)

    def _tariff_year_start(d: pd.Timestamp) -> pd.Timestamp:
        """The April-1 boundary that opens the tariff year containing `d`."""
        return pd.Timestamp(d.year if d.month >= 4 else d.year - 1, 4, 1)

    rows: list[dict] = []

    # Single-rate bills → primary source for each tariff year
    for year_start, grp in bills[bills["is_single_rate"]].groupby(
        bills[bills["is_single_rate"]]["period_from"].apply(_tariff_year_start),
    ):
        canonical = grp.loc[grp["period_days"].idxmax()]
        days = canonical["period_days"]
        rows.append({
            "valid_from": year_start,
            "fw_rate": canonical["fw_rate"],
            "ww_rate": canonical["ww_rate"],
            "fw_standing_per_day": canonical["fw_standing"] / days,
            "ww_standing_per_day": canonical["ww_standing"] / days,
            "rebate_per_day": canonical["rebate"] / days,
            "source": f"single-rate bill {canonical['Source File'][:8]} ({int(days)}d)",
        })

    # Pre-2023-04-01 row from any 2022/23 bill (first April user moved in mid-rate-year)
    pre = bills[bills["period_to"] < pd.Timestamp(2023, 4, 1)]
    if not pre.empty and not any(r["valid_from"] < pd.Timestamp(2023, 4, 1) for r in rows):
        canonical = pre.loc[pre["period_days"].idxmax()]
        days = canonical["period_days"]
        rows.insert(0, {
            "valid_from": pd.Timestamp(1970, 1, 1),
            "fw_rate": canonical["fw_rate"],
            "ww_rate": canonical["ww_rate"],
            "fw_standing_per_day": canonical["fw_standing"] / days,
            "ww_standing_per_day": canonical["ww_standing"] / days,
            "rebate_per_day": canonical["rebate"] / days,
            "source": f"pre-Apr-2023 ({canonical['Source File'][:8]}, {int(days)}d)",
        })

    # Split-rate bills can introduce new tariff years not yet covered (e.g. 2026/27)
    for _, r in bills[~bills["is_single_rate"]].iterrows():
        m = re.search(
            r"Secondary period (\d{4}-\d{2}-\d{2})\s*[→→]\s*(\d{4}-\d{2}-\d{2}).*?"
            r"FW £?([\d.]+)\s*/\s*WW £?([\d.]+)",
            r["notes"] or "",
        )
        if not m:
            continue
        sec_from = pd.to_datetime(m.group(1))
        if sec_from.month != 4 or sec_from.day != 1:
            continue  # not a tariff transition
        if any(h["valid_from"] == sec_from for h in rows):
            continue  # already covered by a single-rate bill
        prior = max((h for h in rows if h["valid_from"] < sec_from),
                    key=lambda h: h["valid_from"], default=None)
        if not prior:
            continue
        rows.append({
            "valid_from": sec_from,
            "fw_rate": float(m.group(3)),
            "ww_rate": float(m.group(4)),
            "fw_standing_per_day": prior["fw_standing_per_day"],
            "ww_standing_per_day": prior["ww_standing_per_day"],
            "rebate_per_day": prior["rebate_per_day"],
            "source": f"split-bill rates; standing carried over from {prior['valid_from']:%Y-%m-%d}",
        })

    return pd.DataFrame(rows).sort_values("valid_from").reset_index(drop=True)


def derive_dd_timeline(tc: pd.DataFrame) -> pd.DataFrame:
    """Build a monthly-DD-effective-from table from Tariff costs rows.

    Anchors each new monthly_dd value on its document_date — slight under-estimate of
    the change-over date (real changes typically take effect 1-2 months later), but
    accurate enough for a daily-paid approximation. Refines automatically when
    new docs are added to the sheet.
    """
    rows = tc.dropna(subset=["doc_date", "monthly_dd"])
    rows = rows[["doc_date", "monthly_dd"]].sort_values("doc_date").reset_index(drop=True)
    # Collapse consecutive duplicates so we only keep change-points
    rows["change"] = rows["monthly_dd"].ne(rows["monthly_dd"].shift())
    rows = rows[rows["change"]].drop(columns="change").reset_index(drop=True)
    return rows.rename(columns={"doc_date": "valid_from", "monthly_dd": "monthly_dd"})


def join_water_cost(
    water: pd.DataFrame,
    history: pd.DataFrame,
    dd_timeline: pd.DataFrame,
) -> pd.DataFrame:
    """Attach per-day water cost columns to each daily reading.

    Each output row gets the rate + £/day standing applicable on its date,
    plus calculated FW/WW subtotals, rebate, total cost, and an annualised
    daily-DD-paid figure for reconciliation.
    """
    out = water.sort_values("date").copy()

    # Tariff history join (rates + standing)
    out = pd.merge_asof(
        out, history.sort_values("valid_from"),
        left_on="date", right_on="valid_from", direction="backward",
    )

    # Per-day cost components (assumes 100% return-to-sewer — bills consistently
    # show waste-water m³ === fresh-water m³, no abatement)
    out["fw_subtotal_gbp"] = out["cons_m3"] * out["fw_rate"] + out["fw_standing_per_day"]
    out["ww_subtotal_gbp"] = (
        out["cons_m3"] * out["ww_rate"] + out["ww_standing_per_day"] - out["rebate_per_day"]
    )
    out["total_cost_gbp"] = out["fw_subtotal_gbp"] + out["ww_subtotal_gbp"]

    # Daily share of monthly DD (annualised so it's stable across months)
    dd_join = pd.merge_asof(
        out[["date"]],
        dd_timeline.sort_values("valid_from"),
        left_on="date", right_on="valid_from", direction="backward",
    )
    out["monthly_dd"] = dd_join["monthly_dd"].values
    out["paid_per_day_gbp"] = out["monthly_dd"] * 12 / 365

    return out


@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading hot water data…")
def load_hot_water() -> pd.DataFrame:
    """Daily district-heater readings + pre-computed costs.

    Pulls from the `Raw data` tab on the Hot Water sheet. The user keeps
    `Total kWh cost (p) per day` and `Total Service charge per day` calculated
    in-sheet, so we just read them and convert pence → £.
    """
    ws = client().open_by_key(SHEET_ID_HOT_WATER).worksheet("Raw data")
    rows = ws.get_all_values()
    df = pd.DataFrame(rows[1:], columns=[c.strip() for c in rows[0]])
    df["date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y", errors="coerce")
    df["unit_rate_p_kwh"] = pd.to_numeric(df["Unit Rate (p/kWh)"], errors="coerce")
    df["service_p_day"] = pd.to_numeric(df["Service Charge (p/day)"], errors="coerce")
    df["meter_read"] = pd.to_numeric(df["Reading"].str.replace(",", "", regex=False), errors="coerce")
    df["kwh_used"] = pd.to_numeric(df["kWh used"], errors="coerce")
    df["kwh_cost_p"] = pd.to_numeric(df["Total kWh cost (p) per day"], errors="coerce")
    df["service_p"] = pd.to_numeric(df["Total Service charge per day"], errors="coerce")
    # Drop rows without a date or without kWh data (e.g. future-padded blank rows)
    df = df.dropna(subset=["date", "kwh_used"]).sort_values("date").reset_index(drop=True)
    df["weekday"] = df["date"].dt.weekday
    df["kwh_cost_gbp"] = df["kwh_cost_p"].fillna(0) / 100
    df["service_gbp"] = df["service_p"].fillna(0) / 100
    df["total_cost_gbp"] = df["kwh_cost_gbp"] + df["service_gbp"]
    return df[[
        "date", "weekday", "meter_read", "kwh_used",
        "unit_rate_p_kwh", "service_p_day",
        "kwh_cost_gbp", "service_gbp", "total_cost_gbp",
    ]]


@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading hot water DD timeline…")
def load_hot_water_dd() -> pd.DataFrame:
    """Read the `DD timeline` step-function from the Hot Water sheet."""
    ws = client().open_by_key(SHEET_ID_HOT_WATER).worksheet("DD timeline")
    rows = ws.get_all_values()
    df = pd.DataFrame(rows[1:], columns=[c.strip() for c in rows[0]])
    df["valid_from"] = pd.to_datetime(df["Valid From"], errors="coerce")
    df["monthly_dd"] = pd.to_numeric(df["Monthly DD (£)"], errors="coerce")
    return df.dropna(subset=["valid_from"]).sort_values("valid_from").reset_index(drop=True)


def join_hot_water_paid(hw: pd.DataFrame, dd_timeline: pd.DataFrame) -> pd.DataFrame:
    """Attach a daily-DD share to each hot-water row for the running-balance chart."""
    out = hw.sort_values("date").copy()
    if dd_timeline.empty:
        out["monthly_dd"] = 0.0
    else:
        joined = pd.merge_asof(
            out[["date"]],
            dd_timeline[["valid_from", "monthly_dd"]],
            left_on="date", right_on="valid_from", direction="backward",
        )
        out["monthly_dd"] = joined["monthly_dd"].fillna(0).values
    out["paid_per_day_gbp"] = out["monthly_dd"] * 12 / 365
    return out
