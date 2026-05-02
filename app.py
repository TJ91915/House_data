"""House dashboard — multi-page entry point."""
import streamlit as st

from lib import (
    load_energy, load_hot_water, load_hot_water_dd,
    load_motion, load_tariffs, load_temperature,
    load_water, load_water_tariffs,
)

st.set_page_config(page_title="House Dashboard", page_icon="🏠", layout="wide")

# Pre-warm all caches so navigating between pages is instant.
# Cached at 2h TTL (see lib.CACHE_TTL).
load_energy()
load_tariffs()
load_temperature()
load_motion()
load_water()
load_water_tariffs()
load_hot_water()
load_hot_water_dd()

pg = st.navigation([
    st.Page("views/summary.py", title="Summary", icon="🏠", default=True),
    st.Page("views/energy.py", title="Energy", icon="⚡"),
    st.Page("views/temperature.py", title="Temperature", icon="🌡️"),
    st.Page("views/motion.py", title="Motion", icon="🚶"),
    st.Page("views/water.py", title="Water", icon="💧"),
    st.Page("views/hot_water.py", title="Hot Water", icon="🔥"),
])
pg.run()
