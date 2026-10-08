from __future__ import annotations

import streamlit as st

from dfs_optimizer.app_ui import apply_app_style


st.set_page_config(
    page_title="NFL Lineup Studio",
    page_icon=":material/sports_football:",
    layout="centered",
    initial_sidebar_state="collapsed",
)

apply_app_style()

for key, default in (
    ("slate", None),
    ("source_name", None),
    ("projections", ()),
    ("projection_key", None),
    ("lineups", ()),
    ("lineup_config_key", None),
    ("current_config_key", None),
    ("lineup_settings", {}),
    ("projection_built_at", None),
    ("salary_content", None),
    ("run_archive", None),
    ("run_archive_name", None),
    ("saved_run_path", None),
    ("current_run_id", None),
    ("generation_warning", None),
):
    st.session_state.setdefault(key, default)

page = st.navigation(
    [
        st.Page(
            "app_pages/setup.py",
            title="Slate & projections",
            icon=":material/query_stats:",
            default=True,
        ),
        st.Page("app_pages/build.py", title="Build lineups", icon=":material/tune:"),
        st.Page("app_pages/results.py", title="Results", icon=":material/analytics:"),
        st.Page("app_pages/backtest.py", title="Backtest", icon=":material/history:"),
        st.Page("app_pages/run_history.py", title="Run history", icon=":material/history_toggle_off:"),
    ],
    position="hidden",
)

page.run()
