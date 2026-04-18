"""House dashboard — multi-page entry point."""
import streamlit as st

from lib import load_energy, load_tariffs, load_temperature

st.set_page_config(page_title="House Dashboard", page_icon="🏠", layout="wide")

# Pre-warm all caches so navigating between pages is instant.
# Cached at 2h TTL (see lib.CACHE_TTL).
load_energy()
load_tariffs()
load_temperature()

pg = st.navigation([
    st.Page("views/energy.py", title="Energy", icon="⚡", default=True),
    st.Page("views/temperature.py", title="Temperature", icon="🌡️"),
])
pg.run()
