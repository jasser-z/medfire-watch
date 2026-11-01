from __future__ import annotations

import os

import streamlit as st
import streamlit.components.v1 as components
from medfire_watch.map_assets import map_asset_version


def render_world_map(debug: bool = False) -> None:
    api = os.environ.get("MEDFIRE_PUBLIC_API_URL", os.environ.get("MEDFIRE_API_URL", "http://127.0.0.1:8000")).rstrip("/")
    st.markdown("""<style>
    iframe[src*="/world-map"] {height: calc(100dvh - 180px) !important; min-height: 530px; border-radius: 18px;
      box-shadow: 0 18px 60px #0005; border: 1px solid #7896aa33;}
    </style>""", unsafe_allow_html=True)
    suffix = '?v=' + map_asset_version() + ('&debug=1' if debug else '')
    components.iframe(f"{api}/world-map{suffix}", height=850, scrolling=False)
