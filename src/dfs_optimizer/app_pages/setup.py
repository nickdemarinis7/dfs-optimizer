from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import os
from pathlib import Path

import streamlit as st

from dfs_optimizer.data_sources.cfb import download_cfb_player_stats
from dfs_optimizer.data_sources.cfb_odds import fetch_cfb_consensus_lines
from dfs_optimizer.app_ui import (
    action_guide,
    apply_platform_theme,
    feature_strip,
    hero,
    optional_label,
    page_kicker,
    section_intro,
    summary_strip,
)
from dfs_optimizer.projections import build_platform_average_projections
from dfs_optimizer.models import Sport
try:
    from dfs_optimizer.services.projections import (
        build_historical_projections,
        download_historical_data,
        historical_data_coverage,
        historical_data_paths,
    )
except ImportError:
    # Streamlit Cloud can keep an already-imported service module alive while
    # pulling a deployment that adds a new export. Reload it once from the
    # updated source tree so the page and service cannot become mismatched.
    from importlib import import_module, reload

    _projection_services = reload(
        import_module("dfs_optimizer.services.projections")
    )
    build_historical_projections = _projection_services.build_historical_projections
    download_historical_data = _projection_services.download_historical_data
    historical_data_coverage = _projection_services.historical_data_coverage
    historical_data_paths = _projection_services.historical_data_paths
from dfs_optimizer.services.player_context import fetch_player_context
from dfs_optimizer.services.role_adjustments import apply_current_role_adjustments
from dfs_optimizer.services.cfb_projections import (
    CFB_FORECAST_MODEL_VERSION,
    apply_cfb_game_lines,
    build_cfb_projections,
    cfb_consensus_lines_csv,
    cfb_projection_input_snapshot,
    estimate_cfb_ownership,
    infer_cfb_season,
    infer_cfb_week,
    infer_cfb_team_names_from_file,
)
from dfs_optimizer.services.slates import infer_slate_period, load_uploaded_salary_file


FORECAST_MODEL_VERSION = "returning-starter-v8"


@st.cache_data(max_entries=8, show_spinner=False)
def _forecast(slate, season: int, week: int, cache_dir: str, model_version: str):
    return build_historical_projections(slate, season, week, cache_dir)


@st.cache_data(ttl=30 * 60, max_entries=8, show_spinner=False)
def _current_player_context(slate, cache_dir: str):
    return fetch_player_context(slate, cache_dir, max_age_hours=.5)


@st.cache_data(ttl=6 * 3600, max_entries=8, show_spinner=False)
def _cfb_forecast(
    slate, season: int, target_week: int, cache_dir: str, model_version: str
):
    return build_cfb_projections(slate, season, target_week, cache_dir)


@st.cache_data(ttl=15 * 60, max_entries=2, show_spinner=False)
def _current_cfb_odds(api_key: str):
    return fetch_cfb_consensus_lines(api_key)


def _odds_api_key() -> str:
    if value := os.environ.get("THE_ODDS_API_KEY"):
        return value
    try:
        return str(st.secrets.get("THE_ODDS_API_KEY", ""))
    except FileNotFoundError:
        return ""


page_kicker(1, "Set up", home=False)
slate = st.session_state.get("slate")
source_name = st.session_state.get("source_name")
salary_content = st.session_state.get("salary_content")

if slate is None:
    hero("Build lineups with a reason.", "Upload one official salary file. Lineup Studio will identify the slate, build role-aware projections, and guide you to a contest-ready portfolio.")
    feature_strip("NFL + CFB", "DraftKings + FanDuel", "Classic + Showdown")
    action_guide(
        1,
        "Upload a salary CSV",
        "Download the player list from DraftKings or FanDuel, then choose that file below. Nothing else is needed yet.",
    )
    upload = st.file_uploader(
        "Choose a DraftKings or FanDuel salary CSV",
        type="csv",
        key="salary-upload",
    )
    if upload:
        try:
            salary_content = upload.getvalue()
            slate = load_uploaded_salary_file(upload.name, salary_content)
            source_name = upload.name
        except (OSError, ValueError) as exc:
            st.error(str(exc))
        else:
            st.session_state["slate"] = slate
            st.session_state["source_name"] = source_name
            st.session_state["salary_content"] = salary_content
            st.session_state["salary_loaded_at"] = datetime.now(timezone.utc)
            st.rerun()

    st.caption("After upload, we’ll confirm the slate and show one clear next step. Saved portfolios are available from Runs above.")
    st.stop()

apply_platform_theme(slate.platform)
hero("Slate confirmed.", "Review the detected contest and projection inputs, then continue to the decisions that matter.")
summary_strip(
    source_name,
    f"{slate.sport.value.upper()} · {slate.platform.value.title()} · "
    f"{slate.contest_format.value.replace('_', ' ').title()} · "
    f"{len(slate.games)} games · {len(slate.players)} players",
)
if st.button("Change salary file", icon=":material/swap_horiz:"):
    for key in (
        "slate", "source_name", "salary_content", "salary_loaded_at", "salary-upload",
        "projections", "base_projections", "role_adjustments", "projection_key",
        "ownership_content", "ownership_name", "ownership_hash",
        "unblended_base_projections", "external_projection_hash",
        "external_projection_content", "external_projection_name",
        "external_projection_matches",
        "nfl_prop_consensus", "nfl_prop_checked_at",
        "nfl_prop_credits_remaining",
        "projection_built_at", "historical_data_health", "player_context",
        "player_context_error", "player_context_built_at", "player_context_attempted",
        "lineups",
        "cfb_game_environments", "cfb_lines_hash", "cfb_lines_name", "cfb_target_week",
        "cfb_odds_warning",
        "cfb_lines_content", "projection_input_snapshot",
        "projection_input_snapshot_name", "cfb_player_context_hash",
        "player_context_source",
        "lineup_config_key", "run_archive", "run_archive_name", "saved_run_path",
        "current_run_id",
        "generation_warning",
        "scenario_analysis",
        "submission_snapshot_key", "submission_snapshot", "saved_submission_path",
        "calibration_record_key", "calibration_record", "saved_calibration_path",
    ):
        st.session_state.pop(key, None)
    st.rerun()

action_guide(
    2,
    "Build this week’s projections",
    "The recommended historical model is selected for you. Confirm the detected week, then continue to player review.",
)

if slate.sport == Sport.CFB:
    st.session_state["player_context"] = ()
    st.session_state["player_context_error"] = None
    st.session_state["player_context_attempted"] = False
    season = infer_cfb_season(slate) or date.today().year
    with st.container(border=True):
        section_intro(
            "College football forecast",
            "Recent player production is blended with the platform baseline, "
            "workload trend, opponent performance, and scoring rules.",
            icon=":material/sports_football:",
        )
        season = int(st.number_input(
            "Season", min_value=2013, max_value=2100, value=season,
            help="The season used for current player game logs.",
        ))
        inferred_week = infer_cfb_week(slate)
        target_week = int(st.number_input(
            "Target week",
            min_value=1,
            max_value=20,
            value=inferred_week or 1,
            help=(
                "Only games before this week are used. The target week's results "
                "are always excluded, even when the data file is refreshed later."
            ),
            key=f"cfb-target-week-{hash(slate)}",
        ))
        refresh_cfb = st.toggle(
            "Force-download latest college data",
            help=(
                "Off uses the six-hour disk cache when available, but still downloads "
                "when that cache is missing or stale. The target-week cutoff prevents leakage."
            ),
        )
        st.caption(
            "Current-season play data: cfbfastR / SportsDataverse. "
            "Players without verified current-season usage are removed unless "
            "you explicitly verify a new starter and provide a projection."
        )
    with st.container(border=True):
        section_intro(
            "Betting context",
            "Optional. Add one row per team to account for expected game scoring. "
            "The adjustment is capped at 6% and is shown during player review.",
            icon=":material/monitoring:",
        )
        odds_api_key = _odds_api_key()
        if odds_api_key:
            st.success(
                "Automatic NCAAF spreads and totals are connected.",
                icon=":material/cloud_done:",
            )
        else:
            st.caption(
                "Add THE_ODDS_API_KEY to Streamlit secrets to fetch current "
                "consensus lines automatically."
            )
        lines_upload = st.file_uploader(
            "Game-lines CSV",
            type="csv",
            key=f"cfb-lines-upload-{hash(slate)}",
            help="Optional manual override. Columns: team, opponent, game_total, spread. Use the salary file's team abbreviations. Negative spread means the listed team is favored.",
        )
        st.caption(
            "Format: team, opponent, game_total, spread · Example: OSU, MICH, 55.5, -7.5"
        )
    lines_content = lines_upload.getvalue() if lines_upload else None
    lines_hash = (
        hashlib.sha256(lines_content).hexdigest()
        if lines_content else ("automatic" if odds_api_key else None)
    )
    projection_key = (
        CFB_FORECAST_MODEL_VERSION, hash(slate), season, target_week,
        str(Path("data/cache/cfb").expanduser()), lines_hash,
    )
    if st.button(
        "Build CFB projections and review players",
        type="primary",
        icon=":material/arrow_forward:",
        width="stretch",
    ):
        try:
            with st.status("Building college projections…", expanded=True) as status:
                if refresh_cfb:
                    status.write("Downloading current player history")
                    download_cfb_player_stats(
                        season, "data/cache/cfb", refresh=True
                    )
                    _cfb_forecast.clear()
                status.write("Scoring recent form and matchup context")
                projections = _cfb_forecast(
                    slate, season, target_week, "data/cache/cfb", CFB_FORECAST_MODEL_VERSION
                )
                automatic_warning = None
                lines_name = lines_upload.name if lines_upload else None
                if not lines_content and odds_api_key:
                    status.write("Fetching current consensus spreads and totals")
                    try:
                        odds = _current_cfb_odds(odds_api_key)
                        stats_source = download_cfb_player_stats(
                            season, "data/cache/cfb"
                        )
                        team_names = infer_cfb_team_names_from_file(
                            slate, stats_source
                        )
                        generated_lines, matched_games = cfb_consensus_lines_csv(
                            slate, odds, team_names
                        )
                        if matched_games:
                            lines_content = generated_lines.encode()
                            lines_name = "The Odds API consensus"
                        else:
                            automatic_warning = (
                                "Current odds were downloaded, but no games matched this slate. "
                                "Projections were left unchanged."
                            )
                    except (OSError, ValueError) as exc:
                        automatic_warning = (
                            f"Automatic betting context was unavailable ({exc}). "
                            "Projections were built without it."
                        )
                if lines_content:
                    status.write("Applying implied team totals")
                    projections, environments = apply_cfb_game_lines(
                        slate, projections, lines_content
                    )
                    st.session_state["cfb_game_environments"] = environments
                    st.session_state["cfb_lines_hash"] = lines_hash
                    st.session_state["cfb_lines_name"] = lines_name
                else:
                    st.session_state["cfb_game_environments"] = {}
                    st.session_state["cfb_lines_hash"] = None
                    st.session_state["cfb_lines_name"] = None
                st.session_state["cfb_odds_warning"] = automatic_warning
                status.update(
                    label="College projections ready",
                    state="complete",
                    expanded=False,
                )
            st.session_state["base_projections"] = projections
            st.session_state["projections"] = projections
            st.session_state["role_adjustments"] = ()
            st.session_state["historical_data_health"] = {}
            st.session_state["projection_key"] = projection_key
            st.session_state["projection_built_at"] = datetime.now(timezone.utc)
            st.session_state["cfb_target_week"] = target_week
            stats_source = download_cfb_player_stats(
                season, "data/cache/cfb"
            )
            st.session_state["projection_input_snapshot"] = (
                cfb_projection_input_snapshot(slate, stats_source, target_week)
            )
            st.session_state["projection_input_snapshot_name"] = (
                f"cfb-{season}-through-week-{target_week - 1}.csv"
            )
            st.session_state["cfb_lines_content"] = lines_content
            st.switch_page("app_pages/build.py")
        except (OSError, ValueError) as exc:
            st.error(f"Could not build the CFB forecast: {exc}")
    projections = (
        st.session_state.get("projections", ())
        if st.session_state.get("projection_key") == projection_key else ()
    )
    if projections:
        platform_average_by_id = {
            player.platform_id: player.platform_average for player in slate.players
        }
        adjusted = sum(
            1 for projection in projections
            if platform_average_by_id.get(projection.platform_id) is not None
            and abs(
                projection.projected_points
                - platform_average_by_id[projection.platform_id]
            ) >= .05
        )
        st.caption(
            f"Ready · {len(projections)} college players projected · "
            f"{adjusted} adjusted with current-season history"
        )
        if st.button(
            "Review college players",
            type="primary",
            icon=":material/arrow_forward:",
            width="stretch",
        ):
            st.switch_page("app_pages/build.py")
    with st.container(border=True):
        st.caption(
            "If the public data source is temporarily unavailable, you can still build "
            "a salary-average baseline."
        )
        if st.button("Use salary-average fallback", width="stretch"):
            fallback = estimate_cfb_ownership(
                slate, build_platform_average_projections(slate)
            )
            environments = {}
            fallback_lines = lines_content
            fallback_lines_name = lines_upload.name if lines_upload else None
            automatic_warning = None
            if not fallback_lines and odds_api_key:
                try:
                    odds = _current_cfb_odds(odds_api_key)
                    stats_source = download_cfb_player_stats(
                        season, "data/cache/cfb"
                    )
                    team_names = infer_cfb_team_names_from_file(
                        slate, stats_source
                    )
                    generated_lines, matched_games = cfb_consensus_lines_csv(
                        slate, odds, team_names
                    )
                    if matched_games:
                        fallback_lines = generated_lines.encode()
                        fallback_lines_name = "The Odds API consensus"
                    else:
                        automatic_warning = (
                            "Current odds were downloaded, but no games matched this slate. "
                            "The fallback was left unchanged."
                        )
                except (OSError, ValueError) as exc:
                    automatic_warning = (
                        f"Automatic betting context was unavailable ({exc}). "
                        "The fallback was built without it."
                    )
            if fallback_lines:
                try:
                    fallback, environments = apply_cfb_game_lines(
                        slate, fallback, fallback_lines
                    )
                except ValueError as exc:
                    st.error(f"Could not apply the game lines: {exc}")
                    st.stop()
            fallback_key = (
                "cfb-platform-average-v5", hash(slate), target_week, lines_hash
            )
            st.session_state["base_projections"] = fallback
            st.session_state["projections"] = fallback
            st.session_state["role_adjustments"] = ()
            st.session_state["historical_data_health"] = {}
            st.session_state["projection_key"] = fallback_key
            st.session_state["projection_built_at"] = datetime.now(timezone.utc)
            st.session_state["cfb_target_week"] = target_week
            st.session_state["cfb_game_environments"] = environments
            st.session_state["cfb_lines_hash"] = lines_hash
            st.session_state["cfb_lines_name"] = fallback_lines_name
            st.session_state["cfb_odds_warning"] = automatic_warning
            st.switch_page("app_pages/build.py")
    st.stop()

method = "Historical forecast"
cache_dir = "data/cache"
optional_label("Advanced projection options")
with st.container(border=True):
    section_intro(
        "Projection model",
        "Historical forecast is recommended. Salary-file average is a fallback when historical data is unavailable.",
        icon=":material/auto_awesome:",
    )
    method = st.segmented_control(
        "Choose a projection method",
        ("Historical forecast", "Salary-file average"),
        default="Historical forecast",
        width="stretch",
        help="Historical forecast uses prior NFL performance. Salary-file average uses the fantasy points supplied by the contest site.",
    )

if method == "Salary-file average":
    base_projections = build_platform_average_projections(slate)
    projection_key = ("salary-average", hash(slate))
    if st.session_state.get("projection_key") != projection_key:
        st.session_state["projection_built_at"] = datetime.now(timezone.utc)
    st.session_state["projection_key"] = projection_key
    if not st.session_state.get("player_context_attempted"):
        st.session_state["player_context_attempted"] = True
        try:
            st.session_state["player_context"] = _current_player_context(slate, cache_dir)
            st.session_state["player_context_source"] = (
                "Sleeper + nflverse depth and injury data"
            )
            st.session_state["player_context_error"] = None
            st.session_state["player_context_built_at"] = datetime.now(timezone.utc)
        except (OSError, ValueError) as exc:
            st.session_state["player_context_error"] = str(exc)
    projections, role_adjustments = apply_current_role_adjustments(
        slate, base_projections, tuple(st.session_state.get("player_context", ()))
    )
    st.session_state["base_projections"] = base_projections
    st.session_state["projections"] = projections
    st.session_state["role_adjustments"] = role_adjustments
    st.session_state["historical_data_health"] = {}
    st.caption("Salary-file averages are a fallback and are not forward-looking weekly projections.")
else:
    inferred = infer_slate_period(slate, Path(cache_dir).expanduser() / "games.csv")
    ready = True
    if inferred:
        season, week, matched, total = inferred
        st.caption(f"Ready to build · {season} Week {week} detected")
        with st.container(border=True):
            section_intro(
                "Detected slate week",
                "Confirm this before building. Refresh data after completed games or major Sunday updates.",
                icon=":material/calendar_month:",
            )
            controls = st.columns(2)
            season = int(controls[0].number_input("Season", 2000, 2100, season))
            week = int(controls[1].number_input("Week", 1, 22, week))
            paths = historical_data_paths(season, cache_dir)
            data_is_stale = paths.age_hours is None or paths.age_hours > 12
            refresh = st.toggle(
                "Refresh historical data", value=bool(paths.missing) or data_is_stale,
                help=(
                    "Downloads the newest completed-game history before projections are built. "
                    "This defaults on when the local data is more than 12 hours old."
                ),
            )
            if paths.age_hours is not None:
                st.caption(f"Historical files updated {paths.age_hours:.1f} hours ago")
            coverage = historical_data_coverage(paths, season)
            if coverage.stats_week is not None or coverage.snap_week is not None:
                st.caption(
                    f"Available through · stats Week {coverage.stats_week or '—'} · "
                    f"snaps Week {coverage.snap_week or '—'}"
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
        "Build projections and review players", type="primary", icon=":material/arrow_forward:",
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
                base_projections = projections
                status.write("Checking current injuries and depth charts")
                try:
                    st.session_state["player_context_attempted"] = True
                    player_context = _current_player_context(slate, cache_dir)
                    st.session_state["player_context"] = player_context
                    st.session_state["player_context_source"] = (
                        "Sleeper + nflverse depth and injury data"
                    )
                    st.session_state["player_context_error"] = None
                    st.session_state["player_context_built_at"] = datetime.now(timezone.utc)
                except (OSError, ValueError) as exc:
                    st.session_state["player_context"] = ()
                    st.session_state["player_context_error"] = str(exc)
                projections, role_adjustments = apply_current_role_adjustments(
                    slate,
                    base_projections,
                    tuple(st.session_state.get("player_context", ())),
                )
                coverage = historical_data_coverage(
                    historical_data_paths(season, cache_dir), season
                )
                status.update(label="Projections ready", state="complete", expanded=False)
            st.session_state["base_projections"] = base_projections
            st.session_state["projections"] = projections
            st.session_state["role_adjustments"] = role_adjustments
            st.session_state["historical_data_health"] = {
                "season": season,
                "target_week": week,
                "stats_week": coverage.stats_week,
                "snap_week": coverage.snap_week,
            }
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
