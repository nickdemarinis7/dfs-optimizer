from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from dfs_optimizer.app_ui import apply_platform_theme, hero, page_kicker, summary_strip
from dfs_optimizer.importers import match_projections
from dfs_optimizer.models import ContestFormat, Position
from dfs_optimizer.optimization import (
    ClassicOptimizationSettings,
    SingleGameOptimizationSettings,
    generate_classic_3max_portfolio,
    generate_classic_lineups,
    generate_single_game_3max_portfolio,
    generate_single_game_lineups,
)
from dfs_optimizer.services.projections import apply_uploaded_ownership


slate = st.session_state.get("slate")
projections = st.session_state.get("projections", ())
if slate is not None:
    apply_platform_theme(slate.platform)
page_kicker(2, "Build")
hero("Shape your portfolio.", "Review the signals, make a few intentional player calls, and let the optimizer build the combinations.")
if slate is None or not projections:
    st.warning("Build projections on the Slate & projections screen first.", icon=":material/arrow_back:")
    st.stop()

projection_by_id = {item.platform_id: item for item in projections}
default_unique = 3 if slate.contest_format == ContestFormat.CLASSIC else 2
with st.popover("Lineup settings", icon=":material/tune:", width="stretch"):
    st.caption("The defaults are tuned for a three-entry tournament portfolio.")
    lineup_count = int(st.number_input(
        "Number of lineups", min_value=1, max_value=20, value=3, step=1,
        key=f"build-lineup-count-{slate.contest_format.value}",
    ))
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
    )
    if slate.contest_format == ContestFormat.CLASSIC:
        maximum_qb_exposure = int(st.number_input(
            "Maximum QB exposure (%)", min_value=5, max_value=100, value=67, step=5,
            key="build-qb-exposure",
        )) / 100
        maximum_dst_exposure = int(st.number_input(
            "Maximum defense exposure (%)", min_value=5, max_value=100, value=67, step=5,
            key="build-dst-exposure",
        )) / 100
        require_qb_stack = st.toggle("Require a QB stack", value=True, key="build-qb-stack")
        require_bring_back = st.toggle(
            "Require an opponent bring-back", value=True, disabled=not require_qb_stack,
            key="build-bring-back",
        )
    else:
        maximum_multiplier_exposure = int(st.number_input(
            "Maximum MVP/Captain exposure (%)", min_value=5, max_value=100, value=67, step=5,
            key="build-multiplier-exposure",
        )) / 100

portfolio_label = "3-max tournament" if lineup_count == 3 else f"{lineup_count}-lineup portfolio"
summary_strip(
    f"{slate.platform.value.title()} {slate.contest_format.value.replace('_', ' ').title()}",
    f"{len(projections)} projected players · {portfolio_label}",
)

players = {p.platform_id: p for p in slate.players if p.platform_id in projection_by_id}
label = lambda pid: f"{players[pid].name} — {players[pid].team} {players[pid].primary_position.value}"
locked = []
with st.container(horizontal=True, wrap=True):
    with st.popover("Player moves", icon=":material/person_edit:"):
        if slate.contest_format == ContestFormat.CLASSIC:
            locked = st.multiselect("Lock", tuple(players), format_func=label, key=f"build-locks-{hash(slate)}")
        excluded = st.multiselect(
            "Exclude", tuple(pid for pid in players if pid not in locked), format_func=label,
            key=f"build-exclusions-{hash(slate)}",
            help="Remove inactive players, backups, or anyone you do not want.",
        )
    with st.popover("Ownership", icon=":material/add_chart:"):
        ownership = st.file_uploader("Projected ownership CSV", type="csv")
        if ownership:
            content = ownership.getvalue()
            ownership_hash = hashlib.sha256(content).hexdigest()
            if st.session_state.get("ownership_hash") != ownership_hash:
                try:
                    projections, matches = apply_uploaded_ownership(
                        slate, projections, ownership.name, content
                    )
                    st.session_state["projections"] = projections
                    st.session_state["ownership_hash"] = ownership_hash
                    st.toast(f"Matched ownership for {matches} players.", icon=":material/check:")
                except (OSError, ValueError) as exc:
                    st.error(f"Could not apply ownership projections: {exc}")
locked_ids, excluded_ids = frozenset(locked), frozenset(excluded)

st.subheader("Player pool")
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
        "Ceiling": projection.ceiling,
        "Status": (player.status or "Available").upper(),
    })

st.caption(f"{len(pool_rows)} players · switch the status filter to explore the slate")
st.dataframe(
    pd.DataFrame(pool_rows),
    column_config={
        "Salary": st.column_config.NumberColumn(format="$%d"),
        "Projection": st.column_config.NumberColumn(format="%.1f"),
        "Ceiling": st.column_config.NumberColumn(format="%.1f"),
    },
    width="stretch",
    hide_index=True,
    height=min(420, 36 + max(1, len(pool_rows)) * 35),
)

news = []
for player in players.values():
    if player.platform_id in excluded_ids:
        continue
    projection = projection_by_id[player.platform_id]
    if player.status:
        news.append(("Status", player.name, player.team, player.status))
    if projection.projected_points < 2:
        news.append(("Low projection", player.name, player.team, f"{projection.projected_points:.2f} points"))
qbs = {}
for player in players.values():
    if player.primary_position == Position.QB and projection_by_id[player.platform_id].projected_points >= 5 and player.platform_id not in excluded_ids:
        qbs.setdefault(player.team, []).append(player.name)
for team, names in qbs.items():
    if len(names) > 1:
        news.append(("QB decision", ", ".join(names), team, "Multiple usable quarterback projections"))
st.subheader("Player signals")
if news:
    signal_types = ("All", *dict.fromkeys(item[0] for item in news))
    signal_view = st.segmented_control(
        "Signal filter",
        signal_types,
        default="All",
        label_visibility="collapsed",
        width="stretch",
    )
    visible_news = [item for item in news if signal_view == "All" or item[0] == signal_view]
    st.caption(f"{len(visible_news)} of {len(news)} signals shown")
    st.dataframe(
        pd.DataFrame(visible_news, columns=("Type", "Player", "Team", "Details")),
        width="stretch",
        hide_index=True,
        height=min(300, 36 + max(1, len(visible_news)) * 35),
    )
else:
    st.caption("No player signals need review.")

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
st.caption(" · ".join(strategy_parts))

config_key = (
    st.session_state.get("projection_key"), st.session_state.get("ownership_hash"),
    hash(slate), tuple(sorted(locked_ids)), tuple(sorted(excluded_ids)),
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
    f"Generate {lineup_count} lineup{'s' if lineup_count != 1 else ''}",
    type="primary", icon=":material/bolt:", width="stretch",
):
    try:
        matches = match_projections(slate, projections)
        with st.status("Optimizing portfolio…", expanded=True) as status:
            if slate.contest_format == ContestFormat.CLASSIC:
                settings = ClassicOptimizationSettings(
                    locked_player_ids=locked_ids, excluded_player_ids=excluded_ids,
                    qb_stack_size=1 if require_qb_stack else 0,
                    require_opponent_bring_back=require_qb_stack and require_bring_back,
                    ceiling_weight=.3, minimum_stack_projection=7 if require_qb_stack else 0,
                    minimum_bring_back_projection=7 if require_qb_stack and require_bring_back else 0,
                    minimum_stack_ceiling=12 if require_qb_stack else 0,
                    minimum_bring_back_ceiling=12 if require_qb_stack and require_bring_back else 0,
                    unique_primary_stacks=require_qb_stack,
                )
                use_tuned_3max = (
                    lineup_count == 3 and minimum_unique == 3
                    and maximum_player_exposure == .67 and maximum_qb_exposure == .67
                    and maximum_dst_exposure == .67 and include_ceiling_lineup
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
                    minimum_multiplier_ceiling=20, minimum_quarterbacks=1,
                    minimum_quarterback_projection=5, minimum_player_projection=.1,
                    maximum_players_per_team=4, maximum_kickers_and_defenses=1,
                    maximum_dst_opponents=1, require_multiplier_receiver_qb=True,
                    ceiling_weight=.3, excluded_player_ids=excluded_ids,
                )
                use_tuned_3max = (
                    lineup_count == 3 and minimum_unique == 2
                    and maximum_player_exposure == .67
                    and maximum_multiplier_exposure == .67 and include_ceiling_lineup
                )
                lineups = (
                    generate_single_game_3max_portfolio(slate, matches, settings)
                    if use_tuned_3max else
                    generate_single_game_lineups(
                        slate, matches, lineup_count, minimum_unique_players=minimum_unique,
                        maximum_player_exposure=maximum_player_exposure,
                        maximum_multiplier_exposure=maximum_multiplier_exposure,
                        settings=settings,
                        lineup_ceiling_weights=(
                            (*([.3] * (lineup_count - 1)), .7)
                            if include_ceiling_lineup else None
                        ),
                    )
                )
            if len(lineups) != lineup_count:
                raise RuntimeError(
                    f"Only {len(lineups)} of {lineup_count} requested lineups could satisfy these settings. "
                    "Try raising exposure or lowering uniqueness."
                )
            status.update(label="Portfolio ready", state="complete", expanded=False)
        st.session_state["lineups"] = lineups
        st.session_state["lineup_config_key"] = config_key
        st.session_state["lineup_settings"] = {
            "portfolio_mode": portfolio_label, "lineups": lineup_count,
            "minimum_unique_players": minimum_unique,
            "maximum_player_exposure": maximum_player_exposure,
            "ceiling_lineup_number": lineup_count if include_ceiling_lineup else None,
        }
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
