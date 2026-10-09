from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd
import streamlit as st

from dfs_optimizer.app_ui import (
    action_guide,
    apply_platform_theme,
    hero,
    optional_label,
    page_kicker,
    section_intro,
    summary_strip,
)
from dfs_optimizer.importers import match_projections
from dfs_optimizer.models import ContestFormat, Position
from dfs_optimizer.optimization import (
    ClassicOptimizationSettings,
    LineupOptimizationError,
    SingleGameOptimizationSettings,
    generate_classic_3max_portfolio,
    generate_classic_lineups,
    generate_single_game_3max_portfolio,
    generate_single_game_lineups,
)
from dfs_optimizer.services.projections import apply_uploaded_ownership
from dfs_optimizer.services.risk import (
    suggest_default_excluded_player_ids,
    suggest_max_once_player_ids,
)
from dfs_optimizer.services.scenarios import simulate_lineups
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


slate = st.session_state.get("slate")
projections = st.session_state.get("projections", ())
if slate is not None:
    apply_platform_theme(slate.platform)
page_kicker(2, "Build")
hero("Review, then build.", "Check the players who need attention. The recommended tournament settings are already filled in.")
if slate is None or not projections:
    st.warning("Build projections on the Slate & projections screen first.", icon=":material/arrow_back:")
    st.stop()

projection_by_id = {item.platform_id: item for item in projections}
player_context = tuple(st.session_state.get("player_context", ()))
context_by_id = {item.platform_id: item for item in player_context}
default_unique = 3 if slate.contest_format == ContestFormat.CLASSIC else 2
players = {p.platform_id: p for p in slate.players if p.platform_id in projection_by_id}
suggested_max_once = suggest_max_once_player_ids(
    slate, tuple(projections), player_context
) & players.keys()
suggested_excluded = (
    suggest_default_excluded_player_ids(slate, tuple(projections), player_context)
    & players.keys()
)
label = lambda pid: f"{players[pid].name} — {players[pid].team} {players[pid].primary_position.value}"
action_guide(
    1,
    "Review flagged players",
    "Check the player table, then exclude anyone who is out or who you do not trust.",
)
if player_context:
    st.caption(
        f"Current role check matched {len(player_context)} of {len(players)} players · "
        "depth-chart and injury signals are active"
    )
elif st.session_state.get("player_context_error"):
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
    require_bring_back = True
else:
    maximum_multiplier_exposure = .34
    maximum_players_per_team = 4
    maximum_kickers_and_defenses = 1

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
                "Require an opponent bring-back", value=True,
                disabled=not require_qb_stack, key="build-bring-back",
                help="Adds an opponent from the same game.",
            )
        else:
            maximum_multiplier_exposure = int(st.number_input(
                "Maximum MVP/Captain exposure (%)", 5, 100, 34, 5,
                key="build-multiplier-exposure",
            )) / 100
            maximum_players_per_team = int(st.number_input(
                "Maximum players from one team", 3, 5, 4,
                key="build-maximum-team-players",
                help="Four is balanced. Five permits aggressive 5–1 game scripts.",
            ))
            maximum_kickers_and_defenses = int(st.number_input(
                "Maximum kickers and defenses", 0, 3, 1,
                key="build-maximum-kicker-defense",
                help="Raise this to test low-scoring or double-kicker constructions.",
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
        ownership = st.file_uploader("Projected ownership CSV (optional)", type="csv")
        if ownership:
            content = ownership.getvalue()
            ownership_hash = hashlib.sha256(content).hexdigest()
            if st.session_state.get("ownership_hash") != ownership_hash:
                try:
                    projections, matches = apply_uploaded_ownership(slate, projections, ownership.name, content)
                    st.session_state["projections"] = projections
                    st.session_state["ownership_hash"] = ownership_hash
                    st.toast(f"Matched ownership for {matches} players.", icon=":material/check:")
                except (OSError, ValueError) as exc:
                    st.error(f"Could not apply ownership projections: {exc}")

portfolio_label = "3-max tournament" if lineup_count == 3 else f"{lineup_count}-lineup portfolio"
summary_strip(
    f"{slate.platform.value.title()} {slate.contest_format.value.replace('_', ' ').title()}",
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
    if status_view == "Available":
        return not status
    if status_view == "Flagged":
        return bool(status)
    if status_view == "Unavailable":
        return status in unavailable_statuses
    return True


pool_rows = []
for player in players.values():
    if not include_in_status_view(player):
        continue
    projection = projection_by_id[player.platform_id]
    pool_rows.append({
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
        "Status": (player.status or "Available").upper(),
        "Role": context_by_id[player.platform_id].role_label if player.platform_id in context_by_id else "—",
    })

st.caption(f"{len(pool_rows)} players · switch the status filter to explore the slate")
st.dataframe(
    pd.DataFrame(pool_rows),
    column_config={
        "Salary": st.column_config.NumberColumn(format="$%d"),
        "Projection": st.column_config.NumberColumn(format="%.1f"),
        "P90": st.column_config.NumberColumn(format="%.1f"),
        "Bust %": st.column_config.NumberColumn(format="%.0f%%"),
    },
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
ownership_coverage = (
    sum(item.projected_ownership is not None for item in projections) / len(projections)
    if projections else 0
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
st.caption(" · ".join(strategy_parts))

action_guide(
    2,
    "Generate your portfolio",
    "If the flagged players look right, use the button below. You’ll move directly to review and download.",
)

config_key = (
    st.session_state.get("projection_key"), st.session_state.get("ownership_hash"),
    hash(slate), tuple(sorted(locked_ids)), tuple(sorted(excluded_ids)), tuple(sorted(limited_ids)),
    lineup_count, minimum_unique, maximum_player_exposure, include_ceiling_lineup,
    maximum_qb_exposure if slate.contest_format == ContestFormat.CLASSIC else None,
    maximum_dst_exposure if slate.contest_format == ContestFormat.CLASSIC else None,
    require_qb_stack if slate.contest_format == ContestFormat.CLASSIC else None,
    require_bring_back if slate.contest_format == ContestFormat.CLASSIC else None,
    maximum_multiplier_exposure if slate.contest_format == ContestFormat.SINGLE_GAME else None,
)
st.session_state["current_config_key"] = config_key
if st.session_state.get("lineups") and st.session_state.get("lineup_config_key") != config_key:
    st.warning("Existing results are stale. Generate again before exporting.", icon=":material/update:")

if st.button(
    f"Generate {lineup_count} lineup{'s' if lineup_count != 1 else ''} and review",
    type="primary", icon=":material/bolt:", width="stretch",
):
    try:
        generation_warning = None
        effective_limited_ids = limited_ids
        effective_player_exposure = maximum_player_exposure
        matches = match_projections(slate, projections)
        with st.status("Optimizing portfolio…", expanded=True) as status:
            if slate.contest_format == ContestFormat.CLASSIC:
                settings = ClassicOptimizationSettings(
                    locked_player_ids=locked_ids, excluded_player_ids=excluded_ids,
                    limited_player_ids=limited_ids,
                    qb_stack_size=1 if require_qb_stack else 0,
                    require_opponent_bring_back=require_qb_stack and require_bring_back,
                    ceiling_weight=.3, minimum_stack_projection=7 if require_qb_stack else 0,
                    minimum_bring_back_projection=7 if require_qb_stack and require_bring_back else 0,
                    minimum_stack_ceiling=12 if require_qb_stack else 0,
                    minimum_bring_back_ceiling=12 if require_qb_stack and require_bring_back else 0,
                    unique_primary_stacks=require_qb_stack,
                    ownership_penalty=.05 if ownership_coverage >= .75 else 0,
                )
                use_tuned_3max = (
                    lineup_count == 3 and minimum_unique == 3
                    and maximum_player_exposure == .67 and maximum_qb_exposure == .67
                    and maximum_dst_exposure == .34 and include_ceiling_lineup
                    and require_qb_stack and require_bring_back
                )
                lineups = (
                    generate_classic_3max_portfolio(slate, matches, settings)
                    if use_tuned_3max else
                    generate_classic_lineups(
                        slate, matches, lineup_count, minimum_unique_players=minimum_unique,
                        settings=settings, maximum_player_exposure=maximum_player_exposure,
                        maximum_qb_exposure=maximum_qb_exposure,
                        maximum_dst_exposure=maximum_dst_exposure,
                        lineup_ceiling_weights=(
                            (*([.3] * (lineup_count - 1)), .7)
                            if include_ceiling_lineup else None
                        ),
                    )
                )
            else:
                settings = SingleGameOptimizationSettings(
                    multiplier_positions=frozenset({Position.QB, Position.RB, Position.WR, Position.TE}),
                    # Avoid a brittle cutoff like Week 5's Bucky Irving projection:
                    # 19.88 multiplied ceiling, yet a winning Captain outcome.
                    minimum_multiplier_ceiling=18, minimum_quarterbacks=1,
                    minimum_quarterback_projection=5, minimum_player_projection=.1,
                    maximum_players_per_team=maximum_players_per_team,
                    maximum_kickers_and_defenses=maximum_kickers_and_defenses,
                    maximum_dst_opponents=1, require_multiplier_receiver_qb=True,
                    ceiling_weight=.3, excluded_player_ids=excluded_ids,
                    limited_player_ids=limited_ids,
                    ownership_penalty=.05 if ownership_coverage >= .75 else 0,
                )
                use_tuned_3max = (
                    lineup_count == 3 and minimum_unique == 2
                    and maximum_player_exposure == .67
                    and maximum_multiplier_exposure == .34 and include_ceiling_lineup
                    and maximum_players_per_team == 4
                    and maximum_kickers_and_defenses == 1
                )
                if use_tuned_3max:
                    try:
                        lineups = generate_single_game_3max_portfolio(
                            slate, matches, settings
                        )
                    except LineupOptimizationError:
                        lineups = generate_single_game_lineups(
                            slate, matches, lineup_count,
                            minimum_unique_players=minimum_unique,
                            maximum_player_exposure=maximum_player_exposure,
                            maximum_multiplier_exposure=maximum_multiplier_exposure,
                            settings=settings,
                            lineup_ceiling_weights=(.3, .3, .7),
                        )
                        generation_warning = (
                            "The extra-strict joint Showdown selector could not form a portfolio. "
                            "These lineups preserve your exposure, uniqueness, player-pool, and "
                            "Captain/MVP limits, but were generated sequentially instead."
                        )
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
                if len(lineups) != lineup_count and limited_ids:
                    effective_limited_ids = frozenset()
                    relaxed_settings = replace(
                        settings, limited_player_ids=effective_limited_ids
                    )
                    lineups = generate_single_game_lineups(
                        slate, matches, lineup_count,
                        minimum_unique_players=minimum_unique,
                        maximum_player_exposure=maximum_player_exposure,
                        maximum_multiplier_exposure=maximum_multiplier_exposure,
                        settings=relaxed_settings,
                        lineup_ceiling_weights=(
                            (*([.3] * (lineup_count - 1)), .7)
                            if include_ceiling_lineup else None
                        ),
                    )
                    if len(lineups) == lineup_count:
                        generation_warning = (
                            "The requested portfolio was infeasible with the selected Max once "
                            "players, so those caps were relaxed. Player exposure, uniqueness, "
                            "and Captain/MVP limits are still enforced."
                        )
                if len(lineups) != lineup_count and maximum_player_exposure < 1:
                    effective_player_exposure = 1.0
                    effective_limited_ids = frozenset()
                    relaxed_settings = replace(
                        settings, limited_player_ids=effective_limited_ids
                    )
                    lineups = generate_single_game_lineups(
                        slate, matches, lineup_count,
                        minimum_unique_players=minimum_unique,
                        maximum_player_exposure=effective_player_exposure,
                        maximum_multiplier_exposure=maximum_multiplier_exposure,
                        settings=relaxed_settings,
                        lineup_ceiling_weights=(
                            (*([.3] * (lineup_count - 1)), .7)
                            if include_ceiling_lineup else None
                        ),
                    )
                    if len(lineups) == lineup_count:
                        generation_warning = (
                            "The requested Showdown exposure caps were infeasible. Max once caps "
                            "were removed and core players may appear in all lineups. Uniqueness "
                            "and distinct Captain/MVP limits are still enforced."
                        )
            if len(lineups) != lineup_count:
                raise RuntimeError(
                    f"Only {len(lineups)} of {lineup_count} requested lineups could satisfy these settings. "
                    "Try raising exposure or lowering uniqueness."
                )
            status.update(label="Portfolio ready", state="complete", expanded=False)
        lineup_settings = {
            "strategy_version": "tournament-defaults-v2",
            "portfolio_mode": portfolio_label, "lineups": lineup_count,
            "minimum_unique_players": minimum_unique,
            "maximum_player_exposure": effective_player_exposure,
            "locked_players": tuple(sorted(players[player_id].name for player_id in locked_ids)),
            "excluded_players": tuple(sorted(players[player_id].name for player_id in excluded_ids)),
            "automatic_exclusion_suggestions": tuple(sorted(
                players[player_id].name for player_id in suggested_excluded
            )),
            "player_context_coverage": len(player_context) / max(1, len(players)),
            "player_context_source": "Sleeper daily player map" if player_context else None,
            "player_context": tuple(
                {
                    "player": players[item.platform_id].name,
                    "depth_chart_position": item.depth_chart_position,
                    "injury_status": item.injury_status,
                    "practice_participation": item.practice_participation,
                    "active": item.active,
                }
                for item in player_context
                if item.platform_id in players
            ),
            "maximum_once_players": tuple(sorted(
                players[player_id].name for player_id in effective_limited_ids
            )),
            "ceiling_lineup_number": lineup_count if include_ceiling_lineup else None,
            "ownership_coverage": ownership_coverage,
            "ownership_penalty": .05 if ownership_coverage >= .75 else 0,
            "constraints_relaxed": bool(generation_warning),
        }
        if slate.contest_format == ContestFormat.CLASSIC:
            lineup_settings.update({
                "maximum_qb_exposure": maximum_qb_exposure,
                "maximum_dst_exposure": maximum_dst_exposure,
                "require_qb_stack": require_qb_stack,
                "require_opponent_bring_back": require_bring_back,
                "minimum_stack_projection": 7 if require_qb_stack else 0,
                "minimum_bring_back_projection": 7 if require_qb_stack and require_bring_back else 0,
            })
        else:
            lineup_settings.update({
                "maximum_multiplier_exposure": maximum_multiplier_exposure,
                "maximum_players_per_team": maximum_players_per_team,
                "maximum_kickers_and_defenses": maximum_kickers_and_defenses,
                "minimum_multiplier_ceiling": 18,
                "minimum_quarterbacks": 1,
            })
        scenario_analysis = simulate_lineups(lineups)
        lineup_settings["scenario_analysis"] = [
            {
                "lineup_number": item.lineup_number,
                "label": item.label,
                "mean": item.mean,
                "p75": item.p75,
                "p90": item.p90,
                "top_rate": item.top_rate,
            }
            for item in scenario_analysis
        ]
        created_at = datetime.now(timezone.utc)
        run_id = (
            f"{created_at:%Y%m%dT%H%M%SZ}-{slate.platform.value}-"
            f"{slate.contest_format.value}-{uuid4().hex[:6]}"
        )
        resolved_label = run_label.strip() or created_at.astimezone().strftime("%a %b %-d, %-I:%M %p")
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
