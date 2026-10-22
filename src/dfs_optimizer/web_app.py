from __future__ import annotations

import tempfile

import streamlit as st

st.set_page_config(
    page_title="Lineup Studio",
    page_icon=":material/sports_football:",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# Streamlit can preserve browser-session objects while a deployment hot-reloads
# new dataclass definitions. Clear that incompatible state whenever the schema
# changes instead of letting old Projection or PlayerContext instances reach
# the new page code.
APP_STATE_SCHEMA_VERSION = 3
if st.session_state.get("_app_state_schema_version") != APP_STATE_SCHEMA_VERSION:
    st.session_state.clear()
    st.session_state["_app_state_schema_version"] = APP_STATE_SCHEMA_VERSION

from dfs_optimizer.app_ui import apply_app_style


apply_app_style()

for key, default in (
    ("slate", None),
    ("source_name", None),
    ("projections", ()),
    ("base_projections", ()),
    ("role_adjustments", ()),
    ("projection_key", None),
    ("lineups", ()),
    ("lineup_config_key", None),
    ("current_config_key", None),
    ("lineup_settings", {}),
    ("projection_built_at", None),
    ("historical_data_health", {}),
    ("cfb_target_week", None),
    ("salary_content", None),
    ("salary_loaded_at", None),
    ("player_context", ()),
    ("player_context_error", None),
    ("player_context_built_at", None),
    ("player_context_attempted", False),
    ("final_status_context", ()),
    ("final_status_content", None),
    ("final_status_name", None),
    ("final_status_hash", None),
    ("final_status_checked_at", None),
    ("final_status_upload_version", 0),
    ("run_archive", None),
    ("run_archive_name", None),
    ("saved_run_path", None),
    ("current_run_id", None),
    ("generation_warning", None),
    ("scenario_analysis", ()),
    ("submission_snapshot_key", None),
    ("submission_snapshot", None),
    ("saved_submission_path", None),
    ("calibration_record_key", None),
    ("calibration_record", None),
    ("saved_calibration_path", None),
):
    st.session_state.setdefault(key, default)

# Hosted filesystems are shared by every visitor and may be erased on restart.
# Give each browser session an isolated temporary run-history directory instead.
if "run_directory" not in st.session_state:
    st.session_state["run_directory"] = tempfile.mkdtemp(prefix="dfs-optimizer-runs-")

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
