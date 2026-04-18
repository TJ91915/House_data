"""House dashboard — multi-page entry point."""
import streamlit as st

st.set_page_config(page_title="House Dashboard", page_icon="🏠", layout="wide")

pg = st.navigation([
    st.Page("views/energy.py", title="Energy", icon="⚡", default=True),
    st.Page("views/temperature.py", title="Temperature", icon="🌡️"),
])
pg.run()
