from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import streamlit as st

from dfs_optimizer.app_ui import (
    apply_platform_theme,
    feature_strip,
    hero,
    page_kicker,
    summary_strip,
)
from dfs_optimizer.projections import build_platform_average_projections
from dfs_optimizer.services.projections import (
    build_historical_projections,
    download_historical_data,
    historical_data_paths,
)
from dfs_optimizer.services.slates import discover_salary_files, infer_slate_period, load_uploaded_salary_file


FORECAST_MODEL_VERSION = "outcome-distributions-v5"


@st.cache_data(max_entries=8)
def _forecast(slate, season: int, week: int, cache_dir: str, model_version: str):
    return build_historical_projections(slate, season, week, cache_dir)


page_kicker(1, "Set up", home=False)
hero("Build your Sunday.", "Drop in a salary file. Lineup Studio handles the contest, slate, and projection setup.")
feature_strip("Live slate workflow", "Correlated simulations", "Post-contest learning")
slate = None
source_name = None
salary_content = None
upload = st.file_uploader(
    "DraftKings or FanDuel salary CSV",
    type="csv",
    label_visibility="collapsed",
)
if upload:
    try:
        salary_content = upload.getvalue()
        slate = load_uploaded_salary_file(upload.name, salary_content)
        source_name = upload.name
    except (OSError, ValueError) as exc:
        st.error(str(exc))

with st.container(horizontal=True):
    with st.popover("Saved slates", icon=":material/folder:"):
        folder = st.text_input("Import folder", value="samples")
        discovered = discover_salary_files(folder)
        if discovered:
            labels = [f"{path.name} — {item.platform.value} / {item.contest_format.value}" for path, item in discovered]
            selected = st.selectbox(
                "Saved salary files", range(len(labels)), index=None,
                placeholder="Choose a file", format_func=lambda i: labels[i],
            )
            if selected is not None and upload is None:
                path, slate = discovered[selected]
                source_name = path.name
                salary_content = path.read_bytes()
        else:
            st.caption("No recognized salary CSV files found in this folder.")
    if st.button("Run history", icon=":material/history_toggle_off:"):
        st.switch_page("app_pages/run_history.py")

if slate is None:
    st.stop()

apply_platform_theme(slate.platform)

if st.session_state.get("slate") != slate:
    for key in (
        "projections", "projection_key", "projection_built_at", "ownership_hash", "lineups",
        "lineup_config_key", "run_archive", "run_archive_name", "saved_run_path",
        "current_run_id",
        "generation_warning",
        "scenario_analysis",
        "submission_snapshot_key", "submission_snapshot", "saved_submission_path",
        "calibration_record_key", "calibration_record", "saved_calibration_path",
    ):
        st.session_state.pop(key, None)
st.session_state["slate"] = slate
st.session_state["source_name"] = source_name
st.session_state["salary_content"] = salary_content

summary_strip(
    source_name,
    f"{slate.platform.value.title()} · "
    f"{slate.contest_format.value.replace('_', ' ').title()} · "
    f"{len(slate.games)} games · {len(slate.players)} players",
)

method = "Historical forecast"
cache_dir = "data/cache"
with st.container(horizontal=True):
    with st.popover("Model", icon=":material/auto_awesome:"):
        method = st.selectbox(
            "Projection method", ("Historical forecast", "Salary-file average")
        )
        if method == "Historical forecast":
            cache_dir = st.text_input("Historical data folder", value="data/cache")

if method == "Salary-file average":
    projections = build_platform_average_projections(slate)
    projection_key = ("salary-average", hash(slate))
    if st.session_state.get("projection_key") != projection_key:
        st.session_state["projection_built_at"] = datetime.now(timezone.utc)
    st.session_state["projections"] = projections
    st.session_state["projection_key"] = projection_key
    st.caption("Salary-file averages are a fallback and are not forward-looking weekly projections.")
else:
    inferred = infer_slate_period(slate, Path(cache_dir).expanduser() / "games.csv")
    ready = True
    if inferred:
        season, week, matched, total = inferred
        st.caption(f"Ready to build · {season} Week {week} detected")
        with st.popover("Week & refresh", icon=":material/calendar_month:"):
            controls = st.columns(2)
            season = int(controls[0].number_input("Season", 2000, 2100, season))
            week = int(controls[1].number_input("Week", 1, 22, week))
            paths = historical_data_paths(season, cache_dir)
            refresh = st.toggle(
                "Refresh historical data", value=bool(paths.missing),
                help="Turn this on after new games are completed.",
            )
    else:
        st.caption("Choose the week because it could not be detected from the salary file.")
        controls = st.columns(2)
        season = int(controls[0].number_input("Season", 2000, 2100, date.today().year))
        selected_week = controls[1].selectbox("Week", range(1, 23), index=None)
        ready = selected_week is not None
        week = int(selected_week) if selected_week else None
        paths = historical_data_paths(season, cache_dir)
        refresh = bool(paths.missing)
    projection_key = (
        "historical", FORECAST_MODEL_VERSION, hash(slate), season, week,
        str(Path(cache_dir).expanduser()),
    )
    if st.button(
        "Build projections", type="primary", icon=":material/auto_awesome:",
        disabled=not ready, width="stretch",
    ):
        try:
            with st.status("Building projections…", expanded=True) as status:
                if refresh or paths.missing:
                    status.write("Downloading historical inputs")
                    download_historical_data(season, cache_dir)
                    _forecast.clear()
                projections = _forecast(
                    slate, season, week, cache_dir, FORECAST_MODEL_VERSION
                )
                status.update(label="Projections ready", state="complete", expanded=False)
            st.session_state["projections"] = projections
            st.session_state["projection_key"] = projection_key
            st.session_state["projection_built_at"] = datetime.now(timezone.utc)
            st.switch_page("app_pages/build.py")
        except (OSError, ValueError) as exc:
            st.error(f"Could not build projections: {exc}")

projections = st.session_state.get("projections", ()) if st.session_state.get("projection_key") == projection_key else ()
if projections:
    st.caption(f"Ready · {len(projections)} of {len(slate.players)} players projected")
    if st.button(
        "Review players",
        type="primary",
        icon=":material/arrow_forward:",
        width="stretch",
    ):
        st.switch_page("app_pages/build.py")
