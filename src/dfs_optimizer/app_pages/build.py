from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd
import streamlit as st

from dfs_optimizer.app_ui import (
    action_guide,
    apply_platform_theme,
    compact_file_uploader,
    hero,
    optional_label,
    page_kicker,
    section_intro,
    summary_strip,
)
from dfs_optimizer.importers import match_projections
from dfs_optimizer.models import ContestFormat, Platform, Position, Sport
from dfs_optimizer.optimization import (
    ClassicOptimizationSettings,
    LineupOptimizationError,
    SingleGameOptimizationSettings,
    generate_classic_3max_portfolio,
    generate_classic_lineups,
    generate_single_game_3max_portfolio,
    generate_single_game_lineups,
)
try:
    from dfs_optimizer.optimization.single_game import (
        DEFAULT_SHOWDOWN_MAX_KICKERS_AND_DEFENSES,
        DEFAULT_SHOWDOWN_MAX_PLAYERS_PER_TEAM,
    )
except ImportError:
    # Streamlit can retain the earlier single-game module while hot-reloading
    # this page after a deployment adds a new exported default.
    from importlib import reload
    from dfs_optimizer.optimization import single_game as _single_game

    _single_game = reload(_single_game)
    DEFAULT_SHOWDOWN_MAX_KICKERS_AND_DEFENSES = (
        _single_game.DEFAULT_SHOWDOWN_MAX_KICKERS_AND_DEFENSES
    )
    DEFAULT_SHOWDOWN_MAX_PLAYERS_PER_TEAM = (
        _single_game.DEFAULT_SHOWDOWN_MAX_PLAYERS_PER_TEAM
    )
from dfs_optimizer.services.projections import (
    apply_uploaded_ownership,
    apply_uploaded_projection_consensus,
)
from dfs_optimizer.services.ownership import (
    NFL_CLASSIC_OWNERSHIP_MODEL_VERSION,
    NFL_SHOWDOWN_OWNERSHIP_MODEL_VERSION,
    estimate_nfl_ownership,
)
from dfs_optimizer.services.opportunity import apply_opportunity_risk
try:
    from dfs_optimizer.services.props import apply_nfl_prop_projection_signals
except ImportError:
    # A running Streamlit process may still hold the module version from
    # before projection-aware prop signals were added.
    from importlib import reload
    from dfs_optimizer.services import props as _props

    _props = reload(_props)
    apply_nfl_prop_projection_signals = _props.apply_nfl_prop_projection_signals
from dfs_optimizer.data_sources.nfl_props import (
    NFL_TEAM_NAMES,
    PROP_MARKETS,
    fetch_nfl_prop_consensus,
)
from dfs_optimizer.data_sources.nfl_news import (
    fetch_nfl_news_candidates,
    nfl_news_snapshot,
)
from dfs_optimizer.services.role_adjustments import apply_current_role_adjustments
from dfs_optimizer.services.player_context import (
    PlayerContext,
    apply_final_status_overrides,
    final_status_csv_template,
    fetch_player_context,
    import_final_status_csv,
    import_player_context_csv,
    player_context_csv_template,
    player_context_snapshot,
    summarize_prelock_context,
    verified_player_context_ids,
)
try:
    from dfs_optimizer.services.risk import (
        suggest_default_excluded_player_ids,
        suggest_max_once_player_ids,
        suggest_player_exposure_limits,
        trusted_showdown_core_ids,
    )
except ImportError:
    # Streamlit can rerun a changed page while retaining an older imported
    # service module. Reload once so newly added helpers are available without
    # requiring the user to repair the session manually.
    from importlib import reload
    from dfs_optimizer.services import risk as _risk

    _risk = reload(_risk)
    suggest_default_excluded_player_ids = _risk.suggest_default_excluded_player_ids
    suggest_max_once_player_ids = _risk.suggest_max_once_player_ids
    suggest_player_exposure_limits = _risk.suggest_player_exposure_limits
    trusted_showdown_core_ids = _risk.trusted_showdown_core_ids
from dfs_optimizer.services.cfb_projections import (
    CFB_FORECAST_MODEL_VERSION,
    historically_verified_cfb_player_ids,
    restore_verified_cfb_starters,
)
from dfs_optimizer.services.confidence import apply_projection_confidence
from dfs_optimizer.services.weekly_context import (
    apply_coach_signals_to_player_context,
    apply_live_weather,
    append_weekly_snapshot_history,
    build_weekly_context,
    coach_signal_csv_template,
    import_coach_signals,
    load_practice_trajectories,
    weekly_context_snapshot,
)
from dfs_optimizer.services.weekly_adjustments import apply_weekly_projection_context
from dfs_optimizer.services import scenarios as _scenarios

if "script_type" not in getattr(
    _scenarios.LineupScenarioAnalysis, "__dataclass_fields__", {}
):
    # Discard the pre-game-script schema retained by a running Streamlit
    # process before creating or serializing any scenario objects.
    from importlib import reload

    _scenarios = reload(_scenarios)
simulate_lineups = _scenarios.simulate_lineups
try:
    from dfs_optimizer.services.run_archive import build_run_archive, save_run_archive
except ImportError:
    # Streamlit Cloud can retain an already-imported module across a Git pull.
    # Reload once so a page update and its service module cannot get out of sync.
    from importlib import reload
    from dfs_optimizer.services import run_archive as _run_archive

    _run_archive = reload(_run_archive)
    build_run_archive = _run_archive.build_run_archive
    save_run_archive = _run_archive.save_run_archive


@st.cache_data(ttl=30 * 60, max_entries=8, show_spinner=False)
def _current_nfl_news(slate):
    return fetch_nfl_news_candidates(slate)


slate = st.session_state.get("slate")
projections = st.session_state.get("projections", ())
if slate is not None:
    apply_platform_theme(slate.platform)
page_kicker(2, "Build")
hero("Make the final calls.", "Review the players who need attention, adjust the recommended strategy if needed, and generate your portfolio.")
if slate is None or not projections:
    st.warning("Build projections on the Slate & projections screen first.", icon=":material/arrow_back:")
    st.stop()


def context_age_minutes() -> float | None:
    checked_at = st.session_state.get("player_context_built_at")
    if checked_at is None:
        return None
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - checked_at).total_seconds() / 60)

player_context = tuple(st.session_state.get("player_context", ()))
canonical_base_projections = (
    tuple(st.session_state.get("base_projections", ())) or tuple(projections)
)
base_projections = restore_verified_cfb_starters(
    slate, canonical_base_projections, player_context
)
prop_matches = 0
prop_adjustments = ()
if slate.sport == Sport.NFL and st.session_state.get("nfl_prop_consensus"):
    base_projections, prop_matches, prop_adjustments = apply_nfl_prop_projection_signals(
        slate,
        base_projections,
        tuple(st.session_state["nfl_prop_consensus"]),
    )
projections, role_adjustments = apply_current_role_adjustments(
    slate, base_projections, player_context
)
weekly_context = tuple(st.session_state.get("weekly_context", ()))
health = st.session_state.get("historical_data_health", {})
practice_trajectories = ()
if health.get("season") and health.get("target_week"):
    practice_trajectories = load_practice_trajectories(
        f"data/cache/weekly_context/{health['season']}-week-{health['target_week']}.jsonl"
    )
projections, weekly_adjustments = apply_weekly_projection_context(
    slate, projections, weekly_context, practice_trajectories
)
projections, opportunity_assessments = apply_opportunity_risk(
    slate, projections, player_context
)
projections = estimate_nfl_ownership(slate, projections)
projections = apply_projection_confidence(
    slate, projections, player_context,
    context_age_minutes=context_age_minutes(),
)
st.session_state["projections"] = projections
st.session_state["role_adjustments"] = role_adjustments
st.session_state["opportunity_assessments"] = opportunity_assessments
st.session_state["weekly_projection_adjustments"] = weekly_adjustments
projection_by_id = {item.platform_id: item for item in projections}
role_adjustment_by_id = {item.platform_id: item for item in role_adjustments}
opportunity_by_id = {item.platform_id: item for item in opportunity_assessments}
context_by_id = {item.platform_id: item for item in player_context}
cfb_game_environments = st.session_state.get("cfb_game_environments", {})
default_unique = 3 if slate.contest_format == ContestFormat.CLASSIC else 2
players = {p.platform_id: p for p in slate.players if p.platform_id in projection_by_id}
suggested_max_once = suggest_max_once_player_ids(
    slate, tuple(projections), player_context
) & players.keys()
suggested_exposure_limits = suggest_player_exposure_limits(
    slate, tuple(projections), player_context, opportunity_assessments
)
if slate.sport == Sport.CFB and slate.contest_format == ContestFormat.CLASSIC:
    # CFB volatility should scale with portfolio size instead of turning every
    # risk flag into the same hard one-lineup constraint.
    suggested_max_once = frozenset()
suggested_excluded = (
    suggest_default_excluded_player_ids(slate, tuple(projections), player_context)
    & players.keys()
)
label = lambda pid: f"{players[pid].name} — {players[pid].team} {players[pid].primary_position.value}"


def store_player_context(
    items, source: str = "Sleeper + nflverse depth and injury data"
) -> None:
    st.session_state["player_context"] = tuple(items)
    st.session_state["player_context_source"] = source
    st.session_state["player_context_error"] = None
    st.session_state["player_context_built_at"] = datetime.now(timezone.utc)
    st.session_state["player_context_attempted"] = True


def store_role_report(player_id: str, expected_role: str | None, note: str) -> None:
    """Merge an auditable pre-lock workload report into live player context."""
    contexts = {
        item.platform_id: item
        for item in st.session_state.get("player_context", ())
    }
    current = contexts.get(player_id) or PlayerContext(
        player_id, None, None, None, None
    )
    contexts[player_id] = replace(
        current,
        expected_role=expected_role,
        role_note=note.strip() or None,
    )
    # Do not call ``store_player_context`` here: a manual report must not make
    # an older automated injury/depth snapshot appear freshly downloaded.
    st.session_state["player_context"] = tuple(contexts.values())
    st.session_state["player_context_error"] = None
    st.session_state["player_context_attempted"] = True


def merge_refreshed_player_context(items) -> tuple[PlayerContext, ...]:
    """Keep human-confirmed workload and final-status facts across refreshes."""
    refreshed = tuple(items)
    saved_reports = {
        item.platform_id: item
        for item in st.session_state.get("player_context", ())
        if item.expected_role
    }
    refreshed = tuple(
        replace(
            item,
            expected_role=saved_reports[item.platform_id].expected_role,
            role_note=saved_reports[item.platform_id].role_note,
        )
        if item.platform_id in saved_reports else item
        for item in refreshed
    )
    refreshed_ids = {item.platform_id for item in refreshed}
    refreshed += tuple(
        item for player_id, item in saved_reports.items()
        if player_id not in refreshed_ids
    )
    return apply_final_status_overrides(
        refreshed, tuple(st.session_state.get("final_status_context", ()))
    )


def add_generation_warning(existing: str | None, message: str) -> str:
    """Preserve every material fallback instead of hiding an earlier warning."""
    return f"{existing} {message}" if existing else message


prelock = summarize_prelock_context(slate, player_context)
cfb_context_confirmed = True
cfb_acknowledged_ids = frozenset()
cfb_pending_key = f"cfb-unverified-selected-{hash(slate)}"
attention_ids = (
    prelock.questionable_player_ids
    | prelock.unavailable_player_ids
    | prelock.backup_quarterback_ids
    | prelock.subordinate_skill_player_ids
)
summary_strip(
    f"{len(attention_ids)} player{'s' if len(attention_ids) != 1 else ''} need review",
    f"{len(prelock.unavailable_player_ids)} unavailable · "
    f"{len(prelock.questionable_player_ids)} injury watch · "
    f"{len(prelock.subordinate_skill_player_ids)} role risk",
)
action_guide(
    1,
    "Review flagged players",
    "Check the player table, then exclude anyone who is out or who you do not trust.",
)
age_minutes = context_age_minutes()
if slate.sport == Sport.NFL:
  with st.container(border=True):
    section_intro(
        "Pre-lock check",
        "Current availability and role signals are checked again before optimization.",
        icon=":material/health_and_safety:",
    )
    data_health = st.session_state.get("historical_data_health", {})
    if data_health:
        stats_week = data_health.get("stats_week")
        snap_week = data_health.get("snap_week")
        target_week = data_health.get("target_week")
        st.caption(
            f"Model inputs · stats through Week {stats_week or '—'} · "
            f"snaps through Week {snap_week or '—'} · forecasting Week {target_week or '—'}"
        )
        expected_week = (target_week - 1) if isinstance(target_week, int) else None
        if expected_week and (
            stats_week is None or stats_week < expected_week
            or snap_week is None or snap_week < expected_week - 1
        ):
            st.warning(
                "Some model inputs are older than expected. Refresh historical data before lock.",
                icon=":material/database:",
            )
    if age_minutes is not None:
        freshness = "just now" if age_minutes < 1 else f"{age_minutes:.0f} minutes ago"
        st.caption(
            f"Injuries and depth chart checked {freshness} · {len(player_context)} matched · "
            f"{len(prelock.unmatched_player_ids)} unmatched"
        )
        if age_minutes > 30:
            st.warning(
                "Role data is more than 30 minutes old. Refresh it before finalizing entries.",
                icon=":material/update:",
            )
    if prelock.unavailable_player_ids:
        st.markdown(
            f":red-badge[{len(prelock.unavailable_player_ids)} unavailable] Automatically excluded"
        )
    if prelock.questionable_player_ids:
        names = ", ".join(
            sorted(players[player_id].name for player_id in prelock.questionable_player_ids if player_id in players)
        )
        st.markdown(f":orange-badge[{len(prelock.questionable_player_ids)} injury watch] {names}")
    if prelock.backup_quarterback_ids:
        names = ", ".join(
            sorted(players[player_id].name for player_id in prelock.backup_quarterback_ids if player_id in players)
        )
        st.markdown(f":blue-badge[{len(prelock.backup_quarterback_ids)} backup QBs] {names}")
    if prelock.subordinate_skill_player_ids:
        names = ", ".join(
            sorted(
                players[player_id].name
                for player_id in prelock.subordinate_skill_player_ids
                if player_id in players
            )[:8]
        )
        st.markdown(
            f":orange-badge[{len(prelock.subordinate_skill_player_ids)} role risks] "
            f"{names} · capped at one lineup by default when projected below 12 points"
        )
    if prelock.unmatched_player_ids:
        unmatched_names = sorted(
            players[player_id].name
            for player_id in prelock.unmatched_player_ids
            if player_id in players
        )
        preview = ", ".join(unmatched_names[:6])
        remainder = len(unmatched_names) - 6
        st.caption(
            "No live role match: " + preview
            + (f" and {remainder} more" if remainder > 0 else "")
            + ". Review these players manually."
        )
    if prelock.games_starting_soon:
        st.warning(
            f"{len(prelock.games_starting_soon)} game(s) start within three hours: "
            + ", ".join(game.split(maxsplit=1)[0] for game in prelock.games_starting_soon),
            icon=":material/schedule:",
        )
    elif prelock.timed_games < prelock.total_games:
        st.caption(
            f"Start times were available for {prelock.timed_games} of {prelock.total_games} games. "
            "Confirm contest lock time on the platform."
        )
    if prelock.started_games:
        st.error(
            f"{len(prelock.started_games)} game(s) appear to have started. Do not submit players from locked games.",
            icon=":material/lock_clock:",
        )
    if weekly_context:
        st.markdown("**Weekly game context**")
        st.caption(
            "Rest, travel, practice participation, weather, and opponent defensive "
            "injuries are preserved with this run. These are decision aids; softer "
            "signals do not silently override the projection model."
        )
        briefing_rows = []
        for item in weekly_context:
            practice = dict(item.practice_counts)
            briefing_rows.append({
                "Team": item.team,
                "Opponent": item.opponent,
                "Rest": item.rest_days if item.rest_days is not None else "—",
                "Travel": f"{item.travel_miles:,} mi" if item.travel_miles else "Home",
                "Weather": (
                    "Indoor" if (item.roof or "").lower() in {"dome", "closed"}
                    else " · ".join(filter(None, (
                        f"{item.temperature_f:.0f}°" if item.temperature_f is not None else "",
                        f"{item.wind_mph:.0f} mph wind" if item.wind_mph is not None else "",
                        f"{item.precipitation_probability:.0f}% precip" if item.precipitation_probability is not None else "",
                        item.weather_summary or "",
                    ))) or "Pending"
                ),
                "Practice": " · ".join(
                    f"{label} {practice.get(label, 0)}" for label in ("DNP", "LP", "FP")
                    if practice.get(label)
                ) or "No flags",
                "Opponent D injuries": len(item.defensive_absences),
                "Watch": " · ".join(item.notes) or "Normal",
            })
        st.dataframe(
            pd.DataFrame(briefing_rows), hide_index=True, width="stretch",
            column_config={
                "Team": st.column_config.TextColumn(width="small"),
                "Opponent": st.column_config.TextColumn(width="small"),
                "Watch": st.column_config.TextColumn(width="large"),
            },
        )
        if weekly_adjustments:
            st.info(
                f"Live weather made a bounded adjustment to {len(weekly_adjustments)} "
                "player projection(s). Open the player table to review the updated "
                "median, range, and confidence reason.",
                icon=":material/air:",
            )
        if health.get("season") and health.get("target_week"):
            if practice_trajectories:
                st.markdown("**Practice movement**")
                st.dataframe(
                    pd.DataFrame([{
                        "Player": item.name,
                        "Team": item.team,
                        "Week": list(item.observations),
                        "Latest": item.latest,
                        "Trend": "Improving" if item.improving else "Monitor",
                    } for item in practice_trajectories]),
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "Player": st.column_config.TextColumn(pinned=True),
                        "Week": st.column_config.ListColumn("Practice week"),
                    },
                )
        coach_actions = st.columns(2)
        coach_actions[0].download_button(
            "Download coach-report template",
            coach_signal_csv_template(slate),
            file_name="coach-role-signals.csv",
            mime="text/csv",
            icon=":material/download:",
            width="stretch",
        )
        with coach_actions[1]:
            coach_upload = compact_file_uploader(
                "Add coach reports",
                "Upload coach reports",
                type=("csv",),
                key=f"coach-signals-{hash(slate)}",
                help="Optional. Upload attributed coach comments using the template.",
            )
        if coach_upload is not None:
            try:
                coach_content = coach_upload.getvalue()
                coach_hash = hashlib.sha256(coach_content).hexdigest()
                coach_signals = import_coach_signals(coach_content)
                st.session_state["coach_signals"] = coach_signals
                coach_changed = st.session_state.get("coach_signals_hash") != coach_hash
                if coach_changed:
                    st.session_state["coach_signals_hash"] = coach_hash
                    st.session_state["player_context"] = apply_coach_signals_to_player_context(
                        slate,
                        tuple(st.session_state.get("player_context", ())),
                        coach_signals,
                    )
                health = st.session_state.get("historical_data_health", {})
                season_value = health.get("season")
                week_value = health.get("target_week")
                if season_value and week_value:
                    st.session_state["weekly_context_snapshot"] = weekly_context_snapshot(
                        weekly_context,
                        season=season_value,
                        week=week_value,
                        checked_at=st.session_state.get("weekly_context_checked_at"),
                        coach_signals=coach_signals,
                        slate=slate,
                        player_context=tuple(st.session_state.get("player_context", ())),
                    )
                st.success(f"Loaded {len(coach_signals)} attributed coach signal(s).")
                if coach_changed:
                    st.rerun()
            except (UnicodeDecodeError, ValueError) as exc:
                st.error(str(exc))
        if coach_signals := st.session_state.get("coach_signals"):
            st.caption(
                "Coach signals · " + ", ".join(
                    f"{item.player}: {item.signal}" for item in coach_signals[:6]
                )
            )
        if st.button(
            "Scan recent team news",
            icon=":material/newspaper:",
            width="stretch",
            key="scan-nfl-news",
        ):
            with st.spinner("Checking attributed team and player reports…"):
                news_candidates = _current_nfl_news(slate)
            st.session_state["nfl_news_candidates"] = news_candidates
            st.session_state["nfl_news_checked_at"] = datetime.now(timezone.utc)
            st.session_state["nfl_news_snapshot"] = nfl_news_snapshot(news_candidates)
        if news_candidates := st.session_state.get("nfl_news_candidates"):
            st.caption(
                "Recent reports matched to slate players. Open the source before "
                "recording a coach-role signal; headlines do not alter projections."
            )
            st.dataframe(
                pd.DataFrame([{
                    "Player": ", ".join(item.matched_players),
                    "Team": item.team,
                    "Topics": list(item.topics),
                    "Report": item.title,
                    "Source": item.source,
                    "Open": item.url,
                } for item in news_candidates[:30]]),
                hide_index=True,
                width="stretch",
                column_config={
                    "Player": st.column_config.TextColumn(pinned=True),
                    "Topics": st.column_config.MultiselectColumn(color="auto"),
                    "Open": st.column_config.LinkColumn("Open", display_text="Read"),
                },
            )
    if st.button(
        "Refresh injuries & depth chart",
        icon=":material/refresh:",
        width="stretch",
        key="refresh-player-context",
    ):
        try:
            with st.spinner("Refreshing injuries and depth charts…"):
                refreshed = fetch_player_context(slate, "data/cache", refresh=True)
            refreshed = merge_refreshed_player_context(refreshed)
            source = "Sleeper + nflverse depth and injury data"
            if st.session_state.get("final_status_context"):
                source += " + uploaded final active/inactive report"
            store_player_context(refreshed, source)
            health = st.session_state.get("historical_data_health", {})
            season_value = health.get("season")
            week_value = health.get("target_week")
            if season_value and week_value:
                checked_at = datetime.now(timezone.utc)
                weekly_context = apply_live_weather(
                    build_weekly_context(
                        slate, season_value, week_value, "data/cache"
                    )
                )
                weekly_snapshot = weekly_context_snapshot(
                    weekly_context,
                    season=season_value,
                    week=week_value,
                    checked_at=checked_at,
                    coach_signals=tuple(st.session_state.get("coach_signals", ())),
                    slate=slate,
                    player_context=refreshed,
                )
                st.session_state["weekly_context"] = weekly_context
                st.session_state["weekly_context_checked_at"] = checked_at
                st.session_state["weekly_context_snapshot"] = weekly_snapshot
                append_weekly_snapshot_history(
                    f"data/cache/weekly_context/{season_value}-week-{week_value}.jsonl",
                    weekly_snapshot,
                )
            st.session_state.pop(f"build-exclusions-{hash(slate)}", None)
            st.session_state.pop(f"build-max-once-{hash(slate)}", None)
            st.toast("Injuries and depth chart are current.", icon=":material/check_circle:")
            st.rerun()
        except (OSError, ValueError) as exc:
            st.session_state["player_context_error"] = str(exc)
            st.error("Injuries and depth chart could not be refreshed. Try again before lock.")
    st.markdown("**Final active/inactive report**")
    st.caption(
        "Optional, but strongest before lock. Enter ACTIVE, INACTIVE, or OUT for "
        "confirmed players. This supersedes stale salary and practice statuses and "
        "is saved inside the run package."
    )
    final_status_actions = st.columns(2)
    final_status_actions[0].download_button(
        "Download status template",
        final_status_csv_template(slate),
        file_name="nfl-final-status-template.csv",
        mime="text/csv",
        icon=":material/download:",
        width="stretch",
    )
    with final_status_actions[1]:
        final_status_upload = compact_file_uploader(
            "Add final statuses",
            "Upload completed status file",
            type=("csv",),
            key=(
                f"final-status-upload-{hash(slate)}-"
                f"{st.session_state.get('final_status_upload_version', 0)}"
            ),
            help="Optional. Upload confirmed ACTIVE, INACTIVE, or OUT statuses using the template.",
        )
    if final_status_upload is not None:
        final_status_content = final_status_upload.getvalue()
        final_status_hash = hashlib.sha256(final_status_content).hexdigest()
        if st.session_state.get("final_status_hash") != final_status_hash:
            try:
                final_statuses = import_final_status_csv(slate, final_status_content)
                combined = apply_final_status_overrides(player_context, final_statuses)
                st.session_state["final_status_context"] = final_statuses
                st.session_state["final_status_content"] = final_status_content
                st.session_state["final_status_name"] = final_status_upload.name
                st.session_state["final_status_hash"] = final_status_hash
                st.session_state["final_status_checked_at"] = datetime.now(timezone.utc)
                store_player_context(
                    combined,
                    "Sleeper + nflverse depth and injury data + uploaded final active/inactive report",
                )
                st.toast(
                    f"Applied {len(final_statuses)} final player statuses.",
                    icon=":material/check_circle:",
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    final_statuses = tuple(st.session_state.get("final_status_context", ()))
    if final_statuses:
        active_count = sum(item.active is True for item in final_statuses)
        coverage = len(final_statuses) / max(1, len(slate.players))
        st.success(
            f"Final report applied: {active_count} active · "
            f"{len(final_statuses) - active_count} inactive/out · "
            f"{coverage:.0%} of slate confirmed",
            icon=":material/verified:",
        )
        if st.button(
            "Clear final-status report",
            icon=":material/delete_sweep:",
            width="stretch",
            key=f"clear-final-status-{hash(slate)}",
        ):
            for key in (
                "final_status_context", "final_status_content", "final_status_name",
                "final_status_hash", "final_status_checked_at",
            ):
                st.session_state.pop(key, None)
            st.session_state["final_status_upload_version"] = (
                st.session_state.get("final_status_upload_version", 0) + 1
            )
            try:
                refreshed = fetch_player_context(slate, "data/cache", max_age_hours=.5)
                refreshed = merge_refreshed_player_context(refreshed)
                store_player_context(refreshed)
            except (OSError, ValueError) as exc:
                st.session_state["player_context"] = ()
                st.session_state["player_context_error"] = str(exc)
                st.session_state["player_context_built_at"] = None
            st.session_state.pop(f"build-exclusions-{hash(slate)}", None)
            st.session_state.pop(f"build-max-once-{hash(slate)}", None)
            st.toast("Final-status overrides cleared.", icon=":material/check_circle:")
            st.rerun()
    odds_key = os.environ.get("THE_ODDS_API_KEY", "")
    if not odds_key:
        try:
            odds_key = str(st.secrets.get("THE_ODDS_API_KEY", ""))
        except (FileNotFoundError, KeyError):
            odds_key = ""
    estimated_prop_cost = len(slate.games) * len(PROP_MARKETS)
    if odds_key:
        if st.button(
            "Refresh betting-market roles",
            icon=":material/query_stats:",
            width="stretch",
            key=f"refresh-nfl-props-{hash(slate)}",
            help=(
                f"Requests {len(PROP_MARKETS)} player-prop markets for each of "
                f"{len(slate.games)} games; estimated maximum cost is "
                f"{estimated_prop_cost} Odds API credits."
            ),
        ):
            try:
                teams = frozenset(
                    NFL_TEAM_NAMES[team]
                    for team in slate.teams
                    if team in NFL_TEAM_NAMES
                )
                with st.spinner("Reading current player-prop markets…"):
                    props, remaining = fetch_nfl_prop_consensus(
                        odds_key, teams=teams
                    )
                st.session_state["nfl_prop_consensus"] = props
                st.session_state["nfl_prop_checked_at"] = datetime.now(timezone.utc)
                st.session_state["nfl_prop_credits_remaining"] = remaining
                st.rerun()
            except (OSError, ValueError) as exc:
                st.error(str(exc))
        if st.session_state.get("nfl_prop_checked_at"):
            remaining = st.session_state.get("nfl_prop_credits_remaining")
            st.caption(
                f"Betting roles · {prop_matches} players matched"
                + (f" · {remaining} API credits remaining" if remaining is not None else "")
            )
    else:
        st.caption(
            "Add THE_ODDS_API_KEY to Streamlit secrets to enable current NFL "
            "player-prop role confirmation."
        )
    st.divider()
    st.markdown("**Late role report**")
    st.caption(
        "Use confirmed beat-report, coach, or inactive-list information when the "
        "depth chart no longer describes the expected workload. The run archive "
        "will save the adjustment and your note."
    )
    role_candidates = sorted(
        (
            player_id for player_id, player in players.items()
            if player.primary_position != Position.DST
        ),
        key=lambda player_id: (players[player_id].team, players[player_id].name),
    )
    role_player_id = st.selectbox(
        "Player affected by the report",
        role_candidates,
        index=None,
        format_func=label,
        placeholder="Choose a player",
        key=f"role-report-player-{hash(slate)}",
        help="Only add a report when it materially changes the expected game-day role.",
    )
    role_choice = st.segmented_control(
        "Expected workload",
        ("Expanded", "Normal", "Committee", "Limited"),
        default="Normal",
        width="stretch",
        help=(
            "Expanded adds 10%; Committee removes 15%; Limited removes 40%. "
            "Normal leaves the median unchanged and suppresses a stale depth-chart penalty."
        ),
        key=f"role-report-choice-{hash(slate)}",
    )
    role_note = st.text_input(
        "What changed?",
        placeholder="Example: coach said he will not lead the backfield",
        key=f"role-report-note-{hash(slate)}",
    )
    role_buttons = st.columns(2)
    if role_buttons[0].button(
        "Apply role report",
        type="primary",
        width="stretch",
        disabled=role_player_id is None or not role_note.strip(),
        key=f"apply-role-report-{hash(slate)}",
    ):
        store_role_report(role_player_id, role_choice.casefold(), role_note)
        st.rerun()
    selected_context = context_by_id.get(role_player_id) if role_player_id else None
    if role_buttons[1].button(
        "Clear selected report",
        width="stretch",
        disabled=selected_context is None or not selected_context.expected_role,
        key=f"clear-role-report-{hash(slate)}",
    ):
        store_role_report(role_player_id, None, "")
        st.rerun()
    active_role_reports = [item for item in player_context if item.expected_role]
    if active_role_reports:
        st.dataframe(
            [
                {
                    "Player": players[item.platform_id].name,
                    "Team": players[item.platform_id].team,
                    "Expected role": item.expected_role.title(),
                    "Evidence": item.role_note or "—",
                }
                for item in active_role_reports
                if item.platform_id in players
            ],
            hide_index=True,
            width="stretch",
        )
else:
    current_projection_key = st.session_state.get("projection_key") or ()
    cfb_model = (
        "recent-form forecast"
        if current_projection_key
        and current_projection_key[0] == CFB_FORECAST_MODEL_VERSION
        else "platform-average baseline"
    )
    with st.container(border=True):
        section_intro(
            "College player check",
            "Combine salary-file designations with a current availability and depth-chart snapshot before lock.",
            icon=":material/sports_football:",
        )
        unavailable_count = len(prelock.unavailable_player_ids)
        questionable_count = len(prelock.questionable_player_ids)
        st.caption(
            f"{unavailable_count} unavailable · {questionable_count} injury watch · "
            f"{cfb_model}"
        )
        st.download_button(
            "Download availability template",
            player_context_csv_template(slate),
            "cfb-player-context.csv",
            "text/csv",
            icon=":material/download:",
            width="stretch",
        )
        context_file = compact_file_uploader(
            "Add availability or depth chart",
            "Current availability / depth-chart CSV",
            type="csv",
            key=f"cfb-player-context-{hash(slate)}",
            help=(
                "Use the template above. Status values such as OUT or QUESTIONABLE, "
                "depth order, and active=false feed directly into exclusions and role limits. "
                "To add a new starter with no season usage, set depth_chart_position=1, "
                "active=true, and enter a positive verified_projection."
            ),
        )
        if context_file is not None:
            content = context_file.getvalue()
            context_hash = hashlib.sha256(content).hexdigest()
            if st.session_state.get("cfb_player_context_hash") != context_hash:
                try:
                    imported_context = import_player_context_csv(slate, content)
                    store_player_context(
                        imported_context,
                        f"Uploaded CFB context: {context_file.name}",
                    )
                    st.session_state["cfb_player_context_hash"] = context_hash
                    st.toast(
                        f"Matched current context for {len(imported_context)} players.",
                        icon=":material/check_circle:",
                    )
                    st.rerun()
                except (UnicodeError, ValueError) as exc:
                    st.error(str(exc), icon=":material/error:")
        if player_context:
            st.caption(
                f"Current role snapshot matched {len(player_context)} players · "
                f"{st.session_state.get('player_context_source', 'uploaded context')}"
            )
        if cfb_model == "recent-form forecast":
            platform_average_by_id = {
                player.platform_id: player.platform_average
                for player in slate.players
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
                f"{adjusted} players were adjusted using current-season game history. "
                "Players without verified current-season usage are removed from the pool."
            )
        ownership_count = sum(
            projection.projected_ownership is not None
            for projection in projections
        )
        if ownership_count:
            st.caption(
                f"Ownership leverage uses a slate-relative estimate for "
                f"{ownership_count} players—not reported contest ownership."
            )
        if cfb_game_environments:
            st.caption(
                f"Betting context matched {len(cfb_game_environments)} teams from "
                f"{st.session_state.get('cfb_lines_name') or 'the uploaded lines file'}. "
                "Projection effects are capped at ±6%."
            )
        elif st.session_state.get("cfb_odds_warning"):
            st.warning(
                st.session_state["cfb_odds_warning"],
                icon=":material/cloud_off:",
            )
        likely_backup_qbs = sorted(
            players[player_id].name
            for player_id in suggested_excluded
            if player_id in players
            and players[player_id].primary_position == Position.QB
        )
        if likely_backup_qbs:
            st.warning(
                "Likely backup QB safeguard: " + ", ".join(likely_backup_qbs)
                + ". They are preselected for exclusion; confirm before building.",
                icon=":material/shield:",
            )
        cfb_context_confirmed = st.checkbox(
            "I checked final availability and starting quarterbacks for this slate",
            key=f"cfb-final-status-confirmed-{hash(slate)}",
            help=(
                "Confirm this only after reviewing official team or conference updates. "
                "The optimizer cannot infer every late scratch from historical usage."
            ),
        )

if not player_context and st.session_state.get("player_context_error"):
    st.warning(
        "Current role data could not be refreshed. Historical safeguards are still active; review backups manually.",
        icon=":material/cloud_off:",
    )

with st.container(border=True):
    section_intro(
        "Your entries",
        "Three lineups is the recommended tournament setup. The optimizer diversifies them automatically.",
        icon=":material/format_list_numbered:",
    )
    lineup_count = int(st.number_input(
        "Number of lineups", min_value=1, max_value=20, value=3, step=1,
        key=f"build-lineup-count-{slate.contest_format.value}",
        help="The number of separate contest entries you want the optimizer to create.",
    ))

minimum_unique = default_unique
maximum_player_exposure = .67
include_ceiling_lineup = True
run_label = ""
locked = []
max_once = list(suggested_max_once)
if slate.contest_format == ContestFormat.CLASSIC:
    maximum_qb_exposure = .67
    maximum_dst_exposure = .34
    require_qb_stack = True
    require_bring_back = False
else:
    maximum_multiplier_exposure = .34
    maximum_players_per_team = DEFAULT_SHOWDOWN_MAX_PLAYERS_PER_TEAM
    maximum_kickers_and_defenses = DEFAULT_SHOWDOWN_MAX_KICKERS_AND_DEFENSES

customize_strategy = st.toggle(
    "Customize strategy",
    help="Reveal expert controls for exposure, stacking, locks, ownership, and lineup diversity.",
)
if customize_strategy:
    optional_label("Advanced strategy")
    with st.container(border=True):
        section_intro(
            "Portfolio strategy",
            "The recommended defaults are selected. Adjust these only when you have a specific tournament plan.",
            icon=":material/tune:",
        )
        minimum_unique = int(st.number_input(
            "Minimum unique players", min_value=1,
            max_value=6 if slate.contest_format == ContestFormat.SINGLE_GAME else 9,
            value=default_unique, step=1,
            key=f"build-minimum-unique-{slate.contest_format.value}",
            help="How many players must change from one lineup to the next.",
        ))
        maximum_player_exposure = int(st.number_input(
            "Maximum player exposure (%)", min_value=5, max_value=100, value=67, step=5,
            key=f"build-player-exposure-{slate.contest_format.value}",
            help="Caps how often a player can appear across the portfolio.",
        )) / 100
        include_ceiling_lineup = st.toggle(
            "Make the final lineup ceiling-focused", value=True,
            key=f"build-ceiling-lineup-{slate.contest_format.value}",
            help="Builds the final entry around upside instead of median projection.",
        )
        run_label = st.text_input(
            "Run label (optional)", placeholder="Wednesday baseline or Sunday final",
            key=f"build-run-label-{slate.platform.value}-{slate.contest_format.value}",
        )
        if slate.contest_format == ContestFormat.CLASSIC:
            maximum_qb_exposure = int(st.number_input(
                "Maximum QB exposure (%)", 5, 100, 67, 5, key="build-qb-exposure",
                help="Limits how many lineups can use the same quarterback.",
            )) / 100
            maximum_dst_exposure = int(st.number_input(
                "Maximum defense exposure (%)", 5, 100, 34, 5, key="build-dst-exposure",
                help="Limits how many lineups can use the same defense.",
            )) / 100
            require_qb_stack = st.toggle(
                "Require a QB stack", value=True, key="build-qb-stack",
                help="Pairs each quarterback with at least one of his receivers.",
            )
            require_bring_back = st.toggle(
                "Require an opponent bring-back", value=False,
                disabled=not require_qb_stack, key="build-bring-back",
                help=(
                    "Optional for large Classic slates. Recent top-field lineups used "
                    "bring-backs often, but not consistently enough to require one in "
                    "every entry."
                ),
            )
        else:
            maximum_multiplier_exposure = int(st.number_input(
                "Maximum MVP/Captain exposure (%)", 5, 100, 34, 5,
                key="build-multiplier-exposure",
            )) / 100
            maximum_players_per_team = int(st.number_input(
                "Maximum players from one team", 3, 5,
                DEFAULT_SHOWDOWN_MAX_PLAYERS_PER_TEAM,
                key="build-maximum-team-players",
                help=(
                    "Five permits 5–1 constructions that repeatedly appear near the "
                    "top of large-field Showdown contests. Choose four only when you "
                    "specifically want more balanced team exposure."
                ),
            ))
            maximum_kickers_and_defenses = int(st.number_input(
                "Maximum kickers and defenses", 0, 3,
                DEFAULT_SHOWDOWN_MAX_KICKERS_AND_DEFENSES,
                key="build-maximum-kicker-defense",
                help=(
                    "Two preserves double-kicker and kicker/defense paths that appeared "
                    "in three of our first six verified Showdown winners."
                ),
            ))

        if slate.contest_format == ContestFormat.CLASSIC:
            locked = st.multiselect(
                "Lock into every lineup",
                tuple(pid for pid in players if pid not in suggested_excluded),
                format_func=label,
                key=f"build-locks-{hash(slate)}",
            )
        max_once = st.multiselect(
            "Max once", tuple(pid for pid in players if pid not in locked),
            default=tuple(pid for pid in suggested_max_once if pid not in locked),
            format_func=label, key=f"build-max-once-{hash(slate)}",
            help="Automatically selected low-floor values can appear in only one lineup.",
        )
        if slate.sport == Sport.NFL:
            consensus = compact_file_uploader(
                "Add external projections",
                "External projections CSV",
                type="csv",
                key=f"external-projections-{hash(slate)}",
                help=(
                    "Columns: name, team, projected_points, with platform_id optional. "
                    "The external median receives 35% weight and is safety-capped."
                ),
            )
            if consensus:
                consensus_content = consensus.getvalue()
                consensus_hash = hashlib.sha256(consensus_content).hexdigest()
                if st.session_state.get("external_projection_hash") != consensus_hash:
                    try:
                        unblended = tuple(
                            st.session_state.get("unblended_base_projections", ())
                        ) or canonical_base_projections
                        blended, consensus_matches = apply_uploaded_projection_consensus(
                            slate, unblended, consensus.name, consensus_content
                        )
                        if not consensus_matches:
                            raise ValueError(
                                "external projection file did not match any slate players"
                            )
                        st.session_state["unblended_base_projections"] = unblended
                        st.session_state["base_projections"] = blended
                        st.session_state["external_projection_hash"] = consensus_hash
                        st.session_state["external_projection_content"] = consensus_content
                        st.session_state["external_projection_name"] = consensus.name
                        st.session_state["external_projection_matches"] = consensus_matches
                        st.toast(
                            f"Blended external projections for {consensus_matches} players.",
                            icon=":material/compare_arrows:",
                        )
                        st.rerun()
                    except (OSError, ValueError) as exc:
                        st.error(f"Could not blend external projections: {exc}")
            if st.session_state.get("external_projection_hash"):
                st.caption(
                    f"Consensus active · {st.session_state.get('external_projection_matches', 0)} "
                    "players matched · 35% external / 65% internal"
                )
                if st.button(
                    "Remove external projection blend",
                    width="stretch",
                    key=f"remove-external-projections-{hash(slate)}",
                ):
                    original = tuple(
                        st.session_state.get("unblended_base_projections", ())
                    )
                    if original:
                        st.session_state["base_projections"] = original
                    for key in (
                        "unblended_base_projections", "external_projection_hash",
                        "external_projection_content", "external_projection_name",
                        "external_projection_matches",
                    ):
                        st.session_state.pop(key, None)
                    # Re-run any still-uploaded ownership file against the
                    # restored internal baseline on the next render.
                    st.session_state.pop("ownership_hash", None)
                    st.rerun()
        ownership = compact_file_uploader(
            "Add projected ownership",
            "Projected ownership CSV",
            type="csv",
            key=f"ownership-upload-{hash(slate)}",
            help=(
                "The free in-house estimate is used automatically. If you have a CSV, "
                "common columns such as Player, Team, Own%, pOWN%, and Projected "
                "Ownership are accepted; unmatched players keep an internal estimate."
            ),
        )
        if ownership:
            content = ownership.getvalue()
            ownership_hash = hashlib.sha256(content).hexdigest()
            if st.session_state.get("ownership_hash") != ownership_hash:
                try:
                    canonical_base_projections, matches = apply_uploaded_ownership(
                        slate, canonical_base_projections, ownership.name, content
                    )
                    base_projections = restore_verified_cfb_starters(
                        slate, canonical_base_projections, player_context
                    )
                    projections, role_adjustments = apply_current_role_adjustments(
                        slate, base_projections, player_context
                    )
                    projections, opportunity_assessments = apply_opportunity_risk(
                        slate, projections, player_context
                    )
                    projections = estimate_nfl_ownership(slate, projections)
                    projections = apply_projection_confidence(
                        slate, projections, player_context,
                        context_age_minutes=context_age_minutes(),
                    )
                    # Keep the canonical model output separate from temporary
                    # context-based starter restorations. If a verification is
                    # corrected later, the player must disappear on rerun.
                    st.session_state["base_projections"] = canonical_base_projections
                    st.session_state["projections"] = projections
                    st.session_state["role_adjustments"] = role_adjustments
                    st.session_state["ownership_hash"] = ownership_hash
                    st.session_state["ownership_content"] = content
                    st.session_state["ownership_name"] = ownership.name
                    st.toast(f"Matched ownership for {matches} players.", icon=":material/check:")
                    st.rerun()
                except (OSError, ValueError) as exc:
                    st.error(f"Could not apply ownership projections: {exc}")

portfolio_label = "3-max tournament" if lineup_count == 3 else f"{lineup_count}-lineup portfolio"
summary_strip(
    f"{slate.sport.value.upper()} · {slate.platform.value.title()} "
    f"{slate.contest_format.value.replace('_', ' ').title()}",
    f"{len(projections)} projected players · {portfolio_label}",
)

st.subheader("Players to review")
status_view = st.segmented_control(
    "Status filter",
    ("All", "Available", "Flagged", "Unavailable"),
    default="Flagged",
    label_visibility="collapsed",
    width="stretch",
)
unavailable_statuses = {"IR", "O", "OUT"}


def include_in_status_view(player) -> bool:
    status = (player.status or "").strip().upper()
    context_flagged = player.platform_id in (
        prelock.questionable_player_ids
        | prelock.unavailable_player_ids
        | prelock.backup_quarterback_ids
        | prelock.subordinate_skill_player_ids
    )
    opportunity_flagged = (
        (opportunity := opportunity_by_id.get(player.platform_id)) is not None
        and opportunity.tier in {"Watch", "Fragile"}
    )
    role_reported = bool(
        player.platform_id in context_by_id
        and context_by_id[player.platform_id].expected_role
    )
    if status_view == "Available":
        return not status and not context_flagged and not opportunity_flagged
    if status_view == "Flagged":
        return bool(status) or context_flagged or opportunity_flagged or role_reported
    if status_view == "Unavailable":
        return (
            status in unavailable_statuses
            or player.platform_id in prelock.unavailable_player_ids
        )
    return True


pool_rows = []
for player in players.values():
    if not include_in_status_view(player):
        continue
    projection = projection_by_id[player.platform_id]
    role_adjustment = role_adjustment_by_id.get(player.platform_id)
    opportunity = opportunity_by_id.get(player.platform_id)
    row = {
        "Player": player.name,
        "Pos": player.primary_position.value,
        "Team": player.team,
        "Opp": player.opponent,
        "Salary": player.salary,
        "Projection": projection.projected_points,
        "P90": projection.p90 if projection.p90 is not None else projection.ceiling,
        "Bust %": (
            100 * projection.bust_probability
            if projection.bust_probability is not None else None
        ),
        "Risk cap %": (
            100 * suggested_exposure_limits[player.platform_id]
            if player.platform_id in suggested_exposure_limits else None
        ),
        "Confidence": projection.confidence_tier or "Unrated",
        "Confidence %": projection.confidence_score,
        "Confidence why": "; ".join(projection.confidence_reasons) or "—",
        "Opportunity": opportunity.tier if opportunity else "Unrated",
        "Opportunity %": opportunity.score if opportunity else None,
        "Opportunity why": "; ".join(opportunity.reasons) if opportunity else "—",
        "Prop markets": projection.prop_market_count,
        "Est. own %": projection.projected_ownership,
        "Status": (player.status or "Available").upper(),
        "Role": context_by_id[player.platform_id].role_label if player.platform_id in context_by_id else "—",
        "News role": (
            context_by_id[player.platform_id].expected_role.title()
            if player.platform_id in context_by_id
            and context_by_id[player.platform_id].expected_role else "—"
        ),
        "News evidence": (
            context_by_id[player.platform_id].role_note or "—"
            if player.platform_id in context_by_id else "—"
        ),
        "Role adj.": role_adjustment.factor if role_adjustment else 1.0,
        "Why": role_adjustment.reason if role_adjustment else "No current-role reduction",
    }
    if slate.sport == Sport.CFB:
        environment = cfb_game_environments.get(player.team.upper())
        row.update({
            "Game total": environment.game_total if environment else None,
            "Implied team": environment.implied_team_total if environment else None,
            "Line adj. %": (
                100 * (environment.projection_multiplier - 1)
                if environment else None
            ),
        })
    pool_rows.append(row)

with st.container(horizontal=True, vertical_alignment="center"):
    st.caption(f"{len(pool_rows)} players · switch the status filter to explore the slate")
    show_advanced_player_metrics = st.toggle(
        "Advanced metrics",
        value=False,
        key=f"advanced-player-metrics-{hash(slate)}",
        help="Show model confidence, ownership, opportunity, betting, and role diagnostics.",
    )
st.dataframe(
    pd.DataFrame(pool_rows),
    column_config={
        "Salary": st.column_config.NumberColumn(format="$%d"),
        "Projection": st.column_config.NumberColumn(format="%.1f"),
        "P90": st.column_config.NumberColumn(format="%.1f"),
        "Bust %": st.column_config.NumberColumn(format="%.0f%%"),
        "Risk cap %": st.column_config.NumberColumn(
            format="%.0f%%",
            help="Automatic portfolio cap from modeled bust risk, floor, current role, and availability.",
        ),
        "Confidence %": st.column_config.NumberColumn(
            format="%.0f%%",
            help="Evidence score from sample size, opportunity stability, outcome range, bust risk, data age, and current role context.",
        ),
        "Confidence": st.column_config.TextColumn(
            help="High is 75+, Medium is 55–74, Low is below 55, and Unrated lacks enough metadata.",
        ),
        "Confidence why": st.column_config.TextColumn(
            help="The evidence that raised or lowered this player's confidence score.",
        ),
        "Opportunity %": st.column_config.NumberColumn(
            format="%.0f%%",
            help="Current-role evidence from recent usage and snap trends, depth order, availability, floor, and bust risk.",
        ),
        "Opportunity": st.column_config.TextColumn(
            help="Strong, Usable, Watch, or Fragile. Fragile roles receive wider downside and stricter portfolio controls.",
        ),
        "Opportunity why": st.column_config.TextColumn(
            help="The evidence behind the current opportunity grade.",
        ),
        "Prop markets": st.column_config.NumberColumn(
            format="%d",
            help="Number of current consensus player-prop markets matched for this player.",
        ),
        "Est. own %": st.column_config.NumberColumn(
            format="%.1f%%",
            help="Estimated from this slate's salary, projection, value, ceiling, and position rank. It is not reported contest ownership.",
        ),
        "Game total": st.column_config.NumberColumn(format="%.1f"),
        "Implied team": st.column_config.NumberColumn(format="%.1f"),
        "Line adj. %": st.column_config.NumberColumn(
            format="%.1f%%",
            help="Projection adjustment from the team's implied score, capped at plus or minus 6%.",
        ),
        "Role adj.": st.column_config.NumberColumn(
            format="%.0f%%",
            help="Bounded multiplier from the current depth chart and any confirmed late role report.",
        ),
        "News role": st.column_config.TextColumn(
            help="Structured pre-lock workload report. This takes priority over nominal depth order.",
        ),
        "News evidence": st.column_config.TextColumn(
            help="The note recorded when the workload report was applied.",
        ),
        "Why": st.column_config.TextColumn(
            help="The specific current-role reason for any projection reduction."
        ),
    },
    column_order=(
        None
        if show_advanced_player_metrics
        else (
            "Player", "Position", "Team", "Salary", "Projection", "P90",
            "Status", "Opportunity",
        )
    ),
    width="stretch",
    hide_index=True,
    height=min(420, 36 + max(1, len(pool_rows)) * 35),
)

with st.container(border=True):
    section_intro(
        "Exclude a player",
        "Unavailable players and clearly subordinate backup quarterbacks are selected automatically. You can override any suggestion.",
        icon=":material/person_remove:",
    )
    excluded = st.multiselect(
        "Players to exclude", tuple(pid for pid in players if pid not in locked),
        default=tuple(pid for pid in suggested_excluded if pid not in locked),
        format_func=label, key=f"build-exclusions-{hash(slate)}",
        help="Excluded players cannot appear in any generated lineup.",
    )
locked_ids, excluded_ids = frozenset(locked), frozenset(excluded)
limited_ids = frozenset(max_once) - locked_ids - excluded_ids
if slate.sport == Sport.CFB:
    current_verified_context_ids = (
        verified_player_context_ids(player_context)
        | historically_verified_cfb_player_ids(tuple(projections))
    )
    pending_unverified_ids = tuple(
        player_id
        for player_id in st.session_state.get(cfb_pending_key, ())
        if player_id in players
        and player_id not in excluded_ids
        and player_id not in current_verified_context_ids
    )
    if pending_unverified_ids:
        with st.container(border=True):
            section_intro(
                "Verify selected college players",
                "These selected players lack both a meaningful current availability row and enough recent game participation to verify automatically.",
                icon=":material/fact_check:",
            )
            st.warning(
                "Confirm every player individually or exclude them. Generation remains blocked until all selected players are resolved.",
                icon=":material/gpp_maybe:",
            )
            st.download_button(
                "Download uncertain-player depth-chart template",
                player_context_csv_template(
                    slate, frozenset(pending_unverified_ids)
                ),
                "cfb-uncertain-player-context.csv",
                "text/csv",
                icon=":material/download:",
                width="stretch",
                help=(
                    "Complete this from an official team or conference source. "
                    "It contains only players selected by the provisional portfolio."
                ),
            )
            focused_context_file = compact_file_uploader(
                "Add completed player checks",
                "Upload completed uncertain-player checks",
                type="csv",
                key=f"cfb-focused-context-{hash(slate)}",
                help=(
                    "Depth order and active status are merged into the existing "
                    "slate context without removing earlier checks."
                ),
            )
            if focused_context_file is not None:
                focused_content = focused_context_file.getvalue()
                focused_hash = hashlib.sha256(focused_content).hexdigest()
                if st.session_state.get("cfb_focused_context_hash") != focused_hash:
                    try:
                        imported_context = import_player_context_csv(
                            slate, focused_content
                        )
                        merged_context = {
                            item.platform_id: item for item in player_context
                        }
                        merged_context.update({
                            item.platform_id: item for item in imported_context
                        })
                        store_player_context(
                            tuple(merged_context.values()),
                            "Official team/conference CFB checks",
                        )
                        st.session_state["cfb_focused_context_hash"] = focused_hash
                        st.toast(
                            f"Matched current context for {len(imported_context)} uncertain players.",
                            icon=":material/check_circle:",
                        )
                        st.rerun()
                    except (UnicodeError, ValueError) as exc:
                        st.error(str(exc), icon=":material/error:")
            cfb_acknowledged_ids = frozenset(st.multiselect(
                "Players personally checked against a current team or conference source",
                pending_unverified_ids,
                format_func=label,
                key=f"cfb-acknowledged-selected-{hash(slate)}",
                help="Selecting a player records a manual override in the run archive. It does not create injury or depth-chart data.",
            ))
ownership_coverage = (
    sum(item.projected_ownership is not None for item in projections) / len(projections)
    if projections else 0
)
ownership_source = (
    "uploaded"
    if ownership_coverage and st.session_state.get("ownership_hash")
    else "slate-relative estimate"
    if ownership_coverage and (
        slate.sport == Sport.CFB
        or slate.sport == Sport.NFL
    )
    else "model-provided"
    if ownership_coverage
    else None
)

strategy_parts = [
    f"{minimum_unique}-player uniqueness",
    f"{maximum_player_exposure:.0%} player exposure cap",
]
if slate.contest_format == ContestFormat.CLASSIC and require_qb_stack:
    strategy_parts.append("QB stack + bring-back" if require_bring_back else "QB stack")
elif slate.contest_format == ContestFormat.SINGLE_GAME:
    strategy_parts.append(f"{maximum_multiplier_exposure:.0%} MVP/Captain cap")
if include_ceiling_lineup:
    strategy_parts.append("final ceiling lineup")
if limited_ids:
    strategy_parts.append(f"{len(limited_ids)} max-once players")
if ownership_coverage >= .75:
    strategy_parts.append("ownership leverage")
summary_strip("Strategy ready", " · ".join(strategy_parts))
if ownership_source == "slate-relative estimate":
    st.caption(
        "Ownership leverage uses the free in-house slate model—not reported contest "
        "ownership. Its archived estimates are compared with final contest ownership "
        "so we can continue calibrating it."
    )

action_guide(
    2,
    "Generate your portfolio",
    "If the flagged players look right, use the button below. You’ll move directly to review and download.",
)

config_key = (
    st.session_state.get("projection_key"), st.session_state.get("ownership_hash"),
    st.session_state.get("external_projection_hash"),
    st.session_state.get("nfl_prop_checked_at"),
    hash(slate), tuple(sorted(locked_ids)), tuple(sorted(excluded_ids)), tuple(sorted(limited_ids)),
    lineup_count, minimum_unique, maximum_player_exposure, include_ceiling_lineup,
    maximum_qb_exposure if slate.contest_format == ContestFormat.CLASSIC else None,
    maximum_dst_exposure if slate.contest_format == ContestFormat.CLASSIC else None,
    require_qb_stack if slate.contest_format == ContestFormat.CLASSIC else None,
    require_bring_back if slate.contest_format == ContestFormat.CLASSIC else None,
    maximum_multiplier_exposure if slate.contest_format == ContestFormat.SINGLE_GAME else None,
    tuple(sorted((item.platform_id, item.factor) for item in role_adjustments)),
    tuple(sorted(cfb_acknowledged_ids)) if slate.sport == Sport.CFB else None,
)
st.session_state["current_config_key"] = config_key
if st.session_state.get("lineups") and st.session_state.get("lineup_config_key") != config_key:
    st.warning("Existing results are stale. Generate again before exporting.", icon=":material/update:")

with st.bottom:
    generate_clicked = st.button(
        f"Generate {lineup_count} lineup{'s' if lineup_count != 1 else ''} and review",
        type="primary", icon=":material/bolt:", width="stretch",
        key="generate-lineups-primary",
    )

if generate_clicked:
    try:
        if slate.sport == Sport.CFB and not cfb_context_confirmed:
            raise RuntimeError(
                "Confirm the final CFB availability and starting-quarterback check before generating."
            )
        generation_warning = None
        quality_scenario_analysis = ()
        classic_candidate_diagnostics = {}
        live_context = player_context
        live_age = context_age_minutes()
        if slate.sport == Sport.NFL and (live_age is None or live_age > 15):
            with st.spinner("Running the final player-news check…"):
                try:
                    live_context = fetch_player_context(
                        slate, "data/cache", max_age_hours=.25
                    )
                    live_context = merge_refreshed_player_context(live_context)
                    source = "Sleeper + nflverse depth and injury data"
                    if st.session_state.get("final_status_context"):
                        source += " + uploaded final active/inactive report"
                    store_player_context(live_context, source)
                except (OSError, ValueError) as exc:
                    st.session_state["player_context_error"] = str(exc)
                    generation_warning = add_generation_warning(generation_warning, (
                        "The final live player-news refresh failed, so the most recent "
                        "available snapshot was used. Confirm player availability before lock."
                    ))
        projections, role_adjustments = apply_current_role_adjustments(
            slate, base_projections, tuple(live_context)
        )
        projections, opportunity_assessments = apply_opportunity_risk(
            slate, projections, tuple(live_context)
        )
        projections = estimate_nfl_ownership(slate, projections)
        projections = apply_projection_confidence(
            slate, projections, tuple(live_context),
            context_age_minutes=context_age_minutes(),
        )
        control_projections = projections
        projections, weekly_adjustments = apply_weekly_projection_context(
            slate,
            projections,
            tuple(st.session_state.get("weekly_context", ())),
            practice_trajectories,
        )
        st.session_state["projections"] = projections
        st.session_state["role_adjustments"] = role_adjustments
        st.session_state["opportunity_assessments"] = opportunity_assessments
        st.session_state["weekly_projection_adjustments"] = weekly_adjustments
        live_excluded = suggest_default_excluded_player_ids(
            slate, tuple(projections), live_context
        ) & players.keys()
        newly_unsafe_locks = locked_ids & live_excluded
        if newly_unsafe_locks:
            names = ", ".join(sorted(players[player_id].name for player_id in newly_unsafe_locks))
            raise RuntimeError(
                f"The latest player news flagged a locked player: {names}. Refresh and review the player pool."
            )
        effective_excluded_ids = excluded_ids | live_excluded
        live_limited = suggest_max_once_player_ids(
            slate, tuple(projections), live_context
        ) & players.keys()
        live_exposure_limits = suggest_player_exposure_limits(
            slate, tuple(projections), live_context, opportunity_assessments
        )
        if slate.sport == Sport.CFB and slate.contest_format == ContestFormat.CLASSIC:
            live_limited = frozenset()
        effective_limited_ids = (
            limited_ids | live_limited
        ) - locked_ids - effective_excluded_ids
        effective_exposure_limits = tuple(sorted(
            (player_id, limit)
            for player_id, limit in live_exposure_limits.items()
            if player_id not in locked_ids
            and player_id not in effective_excluded_ids
            and player_id not in effective_limited_ids
        ))
        effective_player_exposure = maximum_player_exposure
        effective_minimum_unique = minimum_unique
        protected_exposure_limits = effective_exposure_limits
        effective_ownership_penalty = (
            .05 if ownership_source == "uploaded" and ownership_coverage >= .75
            else .025 if slate.sport == Sport.CFB and ownership_coverage >= .75
            else .01 if (
                slate.sport == Sport.NFL
                and ownership_source == "slate-relative estimate"
                and ownership_coverage >= .75
            )
            else 0
        )
        matches = match_projections(slate, projections)
        with st.status("Optimizing portfolio…", expanded=True) as status:
            if slate.contest_format == ContestFormat.CLASSIC:
                settings = ClassicOptimizationSettings(
                    locked_player_ids=locked_ids,
                    excluded_player_ids=effective_excluded_ids,
                    limited_player_ids=effective_limited_ids,
                    player_exposure_limits=effective_exposure_limits,
                    fragile_player_ids=live_limited,
                    maximum_fragile_players=2,
                    qb_stack_size=1 if require_qb_stack else 0,
                    require_opponent_bring_back=require_qb_stack and require_bring_back,
                    ceiling_weight=.3, minimum_stack_projection=7 if require_qb_stack else 0,
                    minimum_bring_back_projection=7 if require_qb_stack and require_bring_back else 0,
                    minimum_stack_ceiling=12 if require_qb_stack else 0,
                    minimum_bring_back_ceiling=12 if require_qb_stack and require_bring_back else 0,
                    unique_primary_stacks=require_qb_stack,
                    ownership_penalty=effective_ownership_penalty,
                    second_tight_end_minimum_projection=(
                        9 if slate.sport == Sport.NFL else 0
                    ),
                    second_tight_end_minimum_floor=(
                        4 if slate.sport == Sport.NFL else 0
                    ),
                    second_tight_end_maximum_bust_probability=(
                        .40 if slate.sport == Sport.NFL else 1
                    ),
                    require_bring_back_for_four_player_team=(
                        slate.sport == Sport.NFL
                    ),
                    avoid_opposing_running_backs=(slate.sport == Sport.NFL),
                    minimum_quarterbacks=(
                        2 if slate.sport == Sport.CFB
                        and slate.platform == Platform.DRAFTKINGS else 0
                    ),
                )
                use_tuned_3max = (
                    slate.sport != Sport.CFB
                    and lineup_count == 3 and minimum_unique == 3
                    and maximum_player_exposure == .67 and maximum_qb_exposure == .67
                    and maximum_dst_exposure == .34 and include_ceiling_lineup
                    and require_qb_stack
                )
                lineups = (
                    generate_classic_3max_portfolio(
                        slate, matches, settings,
                        candidate_diagnostics=classic_candidate_diagnostics,
                    )
                    if use_tuned_3max else
                    generate_classic_lineups(
                        slate, matches, lineup_count, minimum_unique_players=minimum_unique,
                        settings=settings, maximum_player_exposure=maximum_player_exposure,
                        maximum_qb_exposure=maximum_qb_exposure,
                        maximum_dst_exposure=maximum_dst_exposure,
                        lineup_ceiling_weights=(
                            (
                                (.15, .45, .85)
                                if slate.sport == Sport.CFB and lineup_count == 3
                                else (*([.3] * (lineup_count - 1)), .7)
                            )
                            if include_ceiling_lineup else None
                        ),
                        minimum_projection_ratio=(
                            .75 if slate.sport == Sport.CFB and lineup_count == 3 else 0
                        ),
                    )
                )
            else:
                showdown_fragile_ids = frozenset(
                    player_id
                    for player_id in live_limited
                    if players[player_id].primary_position
                    in {Position.RB, Position.WR, Position.TE}
                )
                settings = SingleGameOptimizationSettings(
                    multiplier_positions=frozenset({Position.QB, Position.RB, Position.WR, Position.TE}),
                    # Avoid a brittle cutoff like Week 5's Bucky Irving projection:
                    # 19.88 multiplied ceiling, yet a winning Captain outcome.
                    minimum_multiplier_ceiling=18,
                    maximum_multiplier_bust_probability=.45,
                    minimum_quarterbacks=1,
                    minimum_quarterback_projection=5, minimum_player_projection=.1,
                    maximum_players_per_team=maximum_players_per_team,
                    maximum_kickers_and_defenses=maximum_kickers_and_defenses,
                    maximum_dst_opponents=1, require_multiplier_receiver_qb=True,
                    ceiling_weight=.3, excluded_player_ids=effective_excluded_ids,
                    limited_player_ids=effective_limited_ids,
                    fragile_player_ids=showdown_fragile_ids,
                    maximum_fragile_players=1,
                    bust_probability_penalty=.5,
                    ownership_penalty=effective_ownership_penalty,
                )
                use_tuned_3max = (
                    lineup_count == 3 and minimum_unique == 2
                    and maximum_player_exposure == .67
                    and maximum_multiplier_exposure == .34 and include_ceiling_lineup
                    and maximum_players_per_team
                    == DEFAULT_SHOWDOWN_MAX_PLAYERS_PER_TEAM
                    and maximum_kickers_and_defenses
                    == DEFAULT_SHOWDOWN_MAX_KICKERS_AND_DEFENSES
                )
                if use_tuned_3max:
                    trusted_core_ids = trusted_showdown_core_ids(
                        slate,
                        tuple(projections),
                        tuple(live_context),
                        opportunity_assessments,
                    )
                    try:
                        lineups = generate_single_game_3max_portfolio(
                            slate,
                            matches,
                            settings,
                            universal_core_player_ids=trusted_core_ids,
                        )
                    except LineupOptimizationError:
                        # FanDuel's six-slot format needs 18 appearances across
                        # three lineups. A universal 2-of-3 cap can leave the
                        # strongest joint portfolio infeasible even when a few
                        # verified starters are safe universal cores. Relax
                        # only those players before sacrificing uniqueness or
                        # falling back to order-dependent sequential builds.
                        try:
                            lineups = generate_single_game_3max_portfolio(
                                slate,
                                matches,
                                settings,
                                minimum_unique_players=1,
                                universal_core_player_ids=trusted_core_ids,
                            )
                            effective_minimum_unique = 1
                            generation_warning = add_generation_warning(generation_warning, (
                                "The joint selector used one-player uniqueness and allowed only "
                                "the strongest verified core players in all three lineups. Other "
                                "players remain capped at two appearances."
                            ))
                        except LineupOptimizationError:
                            lineups = generate_single_game_lineups(
                                slate, matches, lineup_count,
                                minimum_unique_players=minimum_unique,
                                maximum_player_exposure=maximum_player_exposure,
                                maximum_multiplier_exposure=maximum_multiplier_exposure,
                                settings=settings,
                                lineup_ceiling_weights=(.3, .3, .7),
                            )
                            generation_warning = add_generation_warning(generation_warning, (
                                "The joint Showdown selector could not form a portfolio. These "
                                "lineups preserve your exposure, uniqueness, player-pool, and "
                                "Captain/MVP limits, but were generated sequentially instead."
                            ))
                else:
                    lineups = generate_single_game_lineups(
                        slate, matches, lineup_count, minimum_unique_players=minimum_unique,
                        maximum_player_exposure=maximum_player_exposure,
                        maximum_multiplier_exposure=maximum_multiplier_exposure,
                        settings=settings,
                        lineup_ceiling_weights=(
                            (*([.3] * (lineup_count - 1)), .7)
                            if include_ceiling_lineup else None
                        ),
                    )
                if len(lineups) != lineup_count and effective_minimum_unique > 1:
                    effective_minimum_unique = 1
                    lineups = generate_single_game_lineups(
                        slate, matches, lineup_count,
                        minimum_unique_players=effective_minimum_unique,
                        maximum_player_exposure=maximum_player_exposure,
                        maximum_multiplier_exposure=maximum_multiplier_exposure,
                        settings=replace(
                            settings, limited_player_ids=effective_limited_ids
                        ),
                        lineup_ceiling_weights=(
                            (*([.3] * (lineup_count - 1)), .7)
                            if include_ceiling_lineup else None
                        ),
                    )
                    if len(lineups) == lineup_count:
                        generation_warning = add_generation_warning(generation_warning, (
                            "The requested Showdown uniqueness was infeasible, so the portfolio "
                            "uses one-player uniqueness. Player exposure, Max once, and distinct "
                            "Captain/MVP limits are still enforced."
                        ))
                if len(lineups) != lineup_count and effective_limited_ids:
                    effective_limited_ids = frozenset()
                    lineups = generate_single_game_lineups(
                        slate, matches, lineup_count,
                        minimum_unique_players=effective_minimum_unique,
                        maximum_player_exposure=maximum_player_exposure,
                        maximum_multiplier_exposure=maximum_multiplier_exposure,
                        settings=replace(settings, limited_player_ids=frozenset()),
                        lineup_ceiling_weights=(
                            (*([.3] * (lineup_count - 1)), .7)
                            if include_ceiling_lineup else None
                        ),
                    )
                    if len(lineups) == lineup_count:
                        generation_warning = add_generation_warning(generation_warning, (
                            "The requested portfolio remained infeasible after reducing uniqueness, "
                            "so Max once caps were relaxed. Player exposure and distinct "
                            "Captain/MVP limits are still enforced."
                        ))
                if (
                    len(lineups) != lineup_count
                    and effective_player_exposure < 1.0
                ):
                    # A six-slot, three-entry FanDuel portfolio needs 18 total
                    # appearances. On a small verified pool, a universal 2-of-3
                    # cap can be mathematically impossible even after reducing
                    # uniqueness and Max-once rules. Exposure is therefore the
                    # final soft constraint to relax, while Captain/MVP exposure,
                    # roster construction, exclusions, and role safeguards stay
                    # intact.
                    # Relax the global cap without turning a volatile value
                    # play into a universal core. Only players with a Strong
                    # current-opportunity grade and a non-extreme bust profile
                    # may reach all three lineups. Everyone else remains at
                    # two of three through a player-specific cap.
                    trusted_core_ids = trusted_showdown_core_ids(
                        slate,
                        tuple(projections),
                        tuple(live_context),
                        opportunity_assessments,
                    )
                    protected_exposure_limits = tuple(sorted(
                        (player_id, .67)
                        for player_id in players
                        if player_id not in trusted_core_ids
                        and player_id not in effective_limited_ids
                        and player_id not in effective_excluded_ids
                    ))
                    effective_player_exposure = 1.0
                    lineups = generate_single_game_lineups(
                        slate, matches, lineup_count,
                        minimum_unique_players=effective_minimum_unique,
                        maximum_player_exposure=effective_player_exposure,
                        maximum_multiplier_exposure=maximum_multiplier_exposure,
                        settings=replace(
                            settings,
                            limited_player_ids=effective_limited_ids,
                            player_exposure_limits=protected_exposure_limits,
                        ),
                        lineup_ceiling_weights=(
                            (*([.3] * (lineup_count - 1)), .7)
                            if include_ceiling_lineup else None
                        ),
                    )
                    if len(lineups) == lineup_count:
                        generation_warning = add_generation_warning(generation_warning, (
                            "The verified player pool could not support a universal two-of-three "
                            "exposure cap, so only high-confidence core players were allowed up "
                            "to 100%. Other players remain capped at two lineups; Captain/MVP "
                            "exposure, exclusions, role safeguards, and lineup uniqueness are "
                            "still enforced."
                        ))
            if len(lineups) != lineup_count:
                if slate.contest_format == ContestFormat.SINGLE_GAME:
                    raise RuntimeError(
                        f"Only {len(lineups)} of {lineup_count} requested lineups could satisfy "
                        "the verified player pool, roster construction, and Captain/MVP limits. "
                        "Review excluded players and multiplier eligibility."
                    )
                raise RuntimeError(
                    f"Only {len(lineups)} of {lineup_count} requested lineups could satisfy these settings. "
                    "Try raising exposure or lowering uniqueness."
                )
            if slate.contest_format == ContestFormat.SINGLE_GAME and lineup_count > 1:
                quality_scenario_analysis = simulate_lineups(
                    lineups, simulations=1_000
                )
                best_p90 = max(item.p90 for item in quality_scenario_analysis)
                competitive = sum(
                    item.p90 >= best_p90 * .80
                    for item in quality_scenario_analysis
                )
                if competitive != lineup_count:
                    quality_warning = (
                        f"{competitive} of {lineup_count} lineups cleared the post-build "
                        "upside benchmark. The portfolio is valid, but review the lower-upside "
                        "lineup before entry; increasing player exposure may strengthen it at "
                        "the cost of more overlap."
                    )
                    generation_warning = add_generation_warning(
                        generation_warning, quality_warning
                    )
            if slate.sport == Sport.CFB:
                selected_player_ids = {
                    entry.player.platform_id
                    for lineup in lineups
                    for entry in lineup.entries
                }
                verified_context_ids = (
                    verified_player_context_ids(tuple(live_context))
                    | historically_verified_cfb_player_ids(tuple(projections))
                )
                unresolved_selected_ids = (
                    selected_player_ids - verified_context_ids
                )
                unacknowledged_ids = (
                    selected_player_ids
                    - verified_context_ids
                    - cfb_acknowledged_ids
                )
                st.session_state[cfb_pending_key] = tuple(sorted(
                    unresolved_selected_ids
                ))
                if unacknowledged_ids:
                    names = ", ".join(sorted(
                        players[player_id].name
                        for player_id in unacknowledged_ids
                    ))
                    raise RuntimeError(
                        "Current verification is required only for these uncertain CFB players: "
                        + names
                        + ". Confirm them in the verification panel or exclude them, then generate again. Established players with recent usage are cleared automatically."
                    )
            shadow_lineups = ()
            if slate.sport == Sport.NFL and weekly_adjustments:
                status.write("Generating no-context shadow portfolio")
                control_matches = match_projections(slate, control_projections)
                try:
                    if slate.contest_format == ContestFormat.CLASSIC:
                        shadow_lineups = (
                            generate_classic_3max_portfolio(
                                slate, control_matches, settings
                            )
                            if use_tuned_3max else
                            generate_classic_lineups(
                                slate,
                                control_matches,
                                lineup_count,
                                minimum_unique_players=effective_minimum_unique,
                                settings=settings,
                                maximum_player_exposure=effective_player_exposure,
                                maximum_qb_exposure=maximum_qb_exposure,
                                maximum_dst_exposure=maximum_dst_exposure,
                                lineup_ceiling_weights=(
                                    (*([.3] * (lineup_count - 1)), .7)
                                    if include_ceiling_lineup else None
                                ),
                            )
                        )
                    else:
                        shadow_settings = replace(
                            settings,
                            limited_player_ids=effective_limited_ids,
                            player_exposure_limits=protected_exposure_limits,
                        )
                        if use_tuned_3max:
                            control_cores = trusted_showdown_core_ids(
                                slate,
                                control_projections,
                                tuple(live_context),
                                opportunity_assessments,
                            )
                            try:
                                shadow_lineups = generate_single_game_3max_portfolio(
                                    slate,
                                    control_matches,
                                    shadow_settings,
                                    minimum_unique_players=effective_minimum_unique,
                                    universal_core_player_ids=control_cores,
                                )
                            except LineupOptimizationError:
                                shadow_lineups = ()
                        if not shadow_lineups:
                            shadow_lineups = generate_single_game_lineups(
                                slate,
                                control_matches,
                                lineup_count,
                                minimum_unique_players=effective_minimum_unique,
                                maximum_player_exposure=effective_player_exposure,
                                maximum_multiplier_exposure=maximum_multiplier_exposure,
                                settings=shadow_settings,
                                lineup_ceiling_weights=(
                                    (*([.3] * (lineup_count - 1)), .7)
                                    if include_ceiling_lineup else None
                                ),
                            )
                    if len(shadow_lineups) != lineup_count:
                        shadow_lineups = ()
                except (LineupOptimizationError, ValueError):
                    shadow_lineups = ()
            status.update(label="Portfolio ready", state="complete", expanded=False)
        lineup_settings = {
            "strategy_version": "tournament-defaults-v5",
            "projection_model_version": (
                st.session_state.get("projection_key", (None,))[0]
                if st.session_state.get("projection_key") else None
            ),
            "portfolio_mode": portfolio_label, "lineups": lineup_count,
            "minimum_unique_players": effective_minimum_unique,
            "requested_minimum_unique_players": minimum_unique,
            "maximum_player_exposure": effective_player_exposure,
            "classic_candidate_diagnostics": classic_candidate_diagnostics or None,
            "nfl_prop_adjustments": tuple({
                "player": item.player,
                "implied_points": round(item.implied_points, 3),
                "original_projection": round(item.original_projection, 3),
                "adjusted_projection": round(item.adjusted_projection, 3),
                "markets": item.markets,
            } for item in prop_adjustments),
            "locked_players": tuple(sorted(players[player_id].name for player_id in locked_ids)),
            "excluded_players": tuple(sorted(
                players[player_id].name for player_id in effective_excluded_ids
            )),
            "automatic_exclusion_suggestions": tuple(sorted(
                players[player_id].name
                for player_id in (
                    (suggested_excluded | live_excluded) & effective_excluded_ids
                )
            )),
            "cfb_game_lines_source": (
                st.session_state.get("cfb_lines_name")
                if slate.sport == Sport.CFB else None
            ),
            "cfb_target_week": (
                st.session_state.get("cfb_target_week")
                if slate.sport == Sport.CFB else None
            ),
            "nfl_target_season": (
                st.session_state.get("historical_data_health", {}).get("season")
                if slate.sport == Sport.NFL else None
            ),
            "nfl_target_week": (
                st.session_state.get("historical_data_health", {}).get("target_week")
                if slate.sport == Sport.NFL else None
            ),
            "nfl_stats_through_week": (
                st.session_state.get("historical_data_health", {}).get("stats_week")
                if slate.sport == Sport.NFL else None
            ),
            "nfl_snaps_through_week": (
                st.session_state.get("historical_data_health", {}).get("snap_week")
                if slate.sport == Sport.NFL else None
            ),
            "cfb_game_lines_team_coverage": (
                len(cfb_game_environments) / max(1, len(slate.teams))
                if slate.sport == Sport.CFB else None
            ),
            "cfb_game_lines_adjustment_cap": (
                .06 if cfb_game_environments else None
            ),
            "player_context_coverage": (
                len(verified_player_context_ids(tuple(live_context)) & players.keys())
                / max(1, len(players))
            ),
            "player_context_source": (
                st.session_state.get("player_context_source") if live_context else None
            ),
            "cfb_final_status_confirmed_at": (
                datetime.now(timezone.utc).isoformat()
                if slate.sport == Sport.CFB and cfb_context_confirmed else None
            ),
            "cfb_manually_acknowledged_players": tuple(sorted(
                players[player_id].name
                for player_id in cfb_acknowledged_ids
                if player_id in players
            )),
            "player_context_checked_at": (
                st.session_state["player_context_built_at"].isoformat()
                if st.session_state.get("player_context_built_at") else None
            ),
            "player_context": tuple(
                {
                    "player": players[item.platform_id].name,
                    "depth_chart_position": item.depth_chart_position,
                    "injury_status": item.injury_status,
                    "practice_participation": item.practice_participation,
                    "active": item.active,
                    "verified_projection": item.verified_projection,
                    "expected_role": item.expected_role,
                    "role_note": item.role_note,
                }
                for item in live_context
                if item.platform_id in players
            ),
            "role_adjustments": tuple(
                {
                    "player": item.player,
                    "team": item.team,
                    "position": item.position,
                    "depth_order": item.depth_order,
                    "factor": item.factor,
                    "original_projection": item.original_projection,
                    "adjusted_projection": item.adjusted_projection,
                    "reason": item.reason,
                }
                for item in role_adjustments
            ),
            "opportunity_assessments": tuple(
                {
                    "player": item.player,
                    "score": item.score,
                    "tier": item.tier,
                    "range_factor": item.range_factor,
                    "reasons": item.reasons,
                }
                for item in opportunity_assessments
            ),
            "maximum_once_players": tuple(sorted(
                players[player_id].name for player_id in effective_limited_ids
            )),
            "automatic_player_exposure_limits": tuple(
                {
                    "player": players[player_id].name,
                    "maximum_exposure": limit,
                }
                for player_id, limit in effective_exposure_limits
                if player_id in players
            ),
            "ceiling_lineup_number": lineup_count if include_ceiling_lineup else None,
            "ownership_coverage": ownership_coverage,
            "ownership_source": ownership_source,
            "external_projection_source": st.session_state.get(
                "external_projection_name"
            ),
            "external_projection_matches": st.session_state.get(
                "external_projection_matches"
            ),
            "external_projection_weight": (
                .35 if st.session_state.get("external_projection_hash") else None
            ),
            "nfl_prop_players_matched": prop_matches or None,
            "nfl_prop_checked_at": (
                st.session_state["nfl_prop_checked_at"].isoformat()
                if st.session_state.get("nfl_prop_checked_at") else None
            ),
            "ownership_model_version": (
                NFL_CLASSIC_OWNERSHIP_MODEL_VERSION
                if ownership_source == "slate-relative estimate"
                and slate.sport == Sport.NFL
                and slate.contest_format == ContestFormat.CLASSIC
                else NFL_SHOWDOWN_OWNERSHIP_MODEL_VERSION
                if ownership_source == "slate-relative estimate"
                and slate.sport == Sport.NFL
                else None
            ),
            "ownership_penalty": effective_ownership_penalty,
            "maximum_fragile_players_per_lineup": (
                2 if slate.contest_format == ContestFormat.CLASSIC
                else 1
            ),
            "lineup_risk_profiles": (
                ("balanced", "upside", "ceiling")
                if slate.sport == Sport.CFB and lineup_count == 3 and include_ceiling_lineup
                else None
            ),
            "constraints_relaxed": bool(generation_warning),
        }
        if slate.contest_format == ContestFormat.CLASSIC:
            lineup_settings.update({
                "maximum_qb_exposure": maximum_qb_exposure,
                "maximum_dst_exposure": maximum_dst_exposure,
                "minimum_quarterbacks": (
                    2 if slate.sport == Sport.CFB
                    and slate.platform == Platform.DRAFTKINGS else 0
                ),
                "minimum_projection_ratio": (
                    .75 if slate.sport == Sport.CFB and lineup_count == 3 else 0
                ),
                "require_qb_stack": require_qb_stack,
                "require_opponent_bring_back": require_bring_back,
                "minimum_stack_projection": 7 if require_qb_stack else 0,
                "minimum_bring_back_projection": 7 if require_qb_stack and require_bring_back else 0,
                "second_tight_end_minimum_projection": (
                    9 if slate.sport == Sport.NFL else 0
                ),
                "second_tight_end_minimum_floor": (
                    4 if slate.sport == Sport.NFL else 0
                ),
                "second_tight_end_maximum_bust_probability": (
                    .40 if slate.sport == Sport.NFL else 1
                ),
                "require_bring_back_for_four_player_team": (
                    slate.sport == Sport.NFL
                ),
                "avoid_opposing_running_backs": slate.sport == Sport.NFL,
            })
        else:
            lineup_settings.update({
                "maximum_multiplier_exposure": maximum_multiplier_exposure,
                "maximum_players_per_team": maximum_players_per_team,
                "maximum_kickers_and_defenses": maximum_kickers_and_defenses,
                "minimum_multiplier_ceiling": 18,
                "minimum_quarterbacks": 1,
            })
        scenario_analysis = (
            quality_scenario_analysis
            if quality_scenario_analysis else simulate_lineups(lineups)
        )
        lineup_settings["scenario_analysis"] = [
            {
                "lineup_number": item.lineup_number,
                "label": item.label,
                "mean": item.mean,
                "p75": item.p75,
                "p90": item.p90,
                "top_rate": item.top_rate,
                "script_type": item.script_type,
                "focal_team": item.focal_team,
                "multiplier_player": item.multiplier_player,
                "multiplier_position": item.multiplier_position,
                "rationale": item.rationale,
            }
            for item in scenario_analysis
        ]
        lineup_settings["weekly_projection_adjustments"] = [
            {
                "platform_id": item.platform_id,
                "player": item.player,
                "factor": item.factor,
                "reasons": list(item.reasons),
            }
            for item in weekly_adjustments
        ]
        if slate.contest_format == ContestFormat.SINGLE_GAME:
            lineup_settings["minimum_portfolio_p90_ratio"] = .80
        created_at = datetime.now(timezone.utc)
        run_id = (
            f"{created_at:%Y%m%dT%H%M%SZ}-{slate.platform.value}-"
            f"{slate.contest_format.value}-{uuid4().hex[:6]}"
        )
        resolved_label = run_label.strip() or created_at.astimezone().strftime("%a %b %-d, %-I:%M %p")
        input_snapshots = {}
        if snapshot := st.session_state.get("projection_input_snapshot"):
            input_snapshots[
                st.session_state.get("projection_input_snapshot_name")
                or "projection-input.csv"
            ] = snapshot
        if lines_snapshot := st.session_state.get("cfb_lines_content"):
            input_snapshots["cfb-game-lines.csv"] = lines_snapshot
        if ownership_snapshot := st.session_state.get("ownership_content"):
            input_snapshots["uploaded-ownership.csv"] = ownership_snapshot
        if consensus_snapshot := st.session_state.get("external_projection_content"):
            input_snapshots["external-projections.csv"] = consensus_snapshot
        if prop_snapshot := st.session_state.get("nfl_prop_consensus"):
            input_snapshots["nfl-prop-consensus.json"] = json.dumps([
                {
                    "player": item.player,
                    "event_id": item.event_id,
                    "markets": dict(item.markets),
                }
                for item in prop_snapshot
            ], indent=2).encode()
        if live_context:
            input_snapshots["player-context.json"] = player_context_snapshot(
                tuple(live_context),
                source=st.session_state.get("player_context_source"),
                checked_at=st.session_state.get("player_context_built_at"),
            )
        if final_status_snapshot := st.session_state.get("final_status_content"):
            input_snapshots["final-status.csv"] = final_status_snapshot
        if weekly_snapshot := st.session_state.get("weekly_context_snapshot"):
            input_snapshots["weekly-context.json"] = weekly_snapshot
        if news_snapshot := st.session_state.get("nfl_news_snapshot"):
            input_snapshots["nfl-news-candidates.json"] = news_snapshot
        run_archive = build_run_archive(
            slate,
            projections,
            lineups,
            lineup_settings,
            st.session_state.get("salary_content"),
            run_id=run_id,
            run_label=resolved_label,
            created_at=created_at,
            projection_built_at=st.session_state.get("projection_built_at"),
            input_snapshots=input_snapshots,
            shadow_projections=(control_projections if shadow_lineups else None),
            shadow_lineups=shadow_lineups,
            experiment=(
                {
                    "name": "weekly-context-ab-v1",
                    "treatment": "weekly context enabled",
                    "control": "weekly projection adjustments disabled",
                    "primary_portfolio": "treatment",
                    "shadow_lineup_count": len(shadow_lineups),
                }
                if shadow_lineups else None
            ),
        )
        archive_name = (
            f"dfs-run-{slate.platform.value}-{slate.contest_format.value}.zip"
        )
        saved_run_path = None
        try:
            saved_run_path = save_run_archive(
                run_archive, slate,
                directory=st.session_state["run_directory"],
                created_at=created_at, run_id=run_id,
            )
        except OSError:
            # Hosted Streamlit filesystems may be ephemeral or read-only. The
            # in-session download below remains the durable handoff.
            pass
        st.session_state["lineups"] = lineups
        st.session_state["lineup_config_key"] = config_key
        st.session_state["lineup_settings"] = lineup_settings
        st.session_state["run_archive"] = run_archive
        st.session_state["run_archive_name"] = archive_name
        st.session_state["saved_run_path"] = str(saved_run_path) if saved_run_path else None
        st.session_state["current_run_id"] = run_id
        st.session_state["generation_warning"] = generation_warning
        st.session_state["scenario_analysis"] = scenario_analysis
        st.session_state["shadow_lineups"] = shadow_lineups
        st.session_state["shadow_projections"] = (
            control_projections if shadow_lineups else ()
        )
        st.switch_page("app_pages/results.py")
    except (ValueError, RuntimeError) as exc:
        st.error(f"Could not generate lineups: {exc}")

with st.container(horizontal=True, horizontal_alignment="distribute"):
    if st.button("Back", icon=":material/arrow_back:"):
        st.switch_page("app_pages/setup.py")
    if st.session_state.get("lineups") and st.button(
        "View current results", icon=":material/arrow_forward:"
    ):
        st.switch_page("app_pages/results.py")
