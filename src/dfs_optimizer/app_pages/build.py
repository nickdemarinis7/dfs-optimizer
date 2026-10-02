from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from dfs_optimizer.app_ui import page_kicker
from dfs_optimizer.importers import match_projections
from dfs_optimizer.models import ContestFormat, Position
from dfs_optimizer.optimization import (
    ClassicOptimizationSettings,
    SingleGameOptimizationSettings,
    generate_classic_3max_portfolio,
    generate_single_game_3max_portfolio,
)
from dfs_optimizer.services.projections import apply_uploaded_ownership


slate = st.session_state.get("slate")
projections = st.session_state.get("projections", ())
page_kicker(2, "Build")
st.title("Build your lineups")
st.caption("Make any final player decisions, then generate your three-entry portfolio.")
st.progress(2 / 3, text="Lineup build")
if slate is None or not projections:
    st.warning("Build projections on the Slate & projections screen first.", icon=":material/arrow_back:")
    st.stop()

with st.expander("Add ownership projections", icon=":material/add_chart:"):
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

projection_by_id = {item.platform_id: item for item in projections}
st.badge(
    f"{slate.platform.value.title()} · {slate.contest_format.value.replace('_', ' ').title()}",
    icon=":material/sports_football:",
    color="blue",
)

with st.expander(f"Player pool · {len(projections)} projected", icon=":material/table_view:"):
    st.dataframe(pd.DataFrame([{
        "Player": player.name, "Position": player.primary_position.value,
        "Team": player.team, "Opponent": player.opponent, "Salary": player.salary,
        "Projection": projection_by_id[player.platform_id].projected_points if player.platform_id in projection_by_id else None,
        "Ceiling": projection_by_id[player.platform_id].ceiling if player.platform_id in projection_by_id else None,
        "Status": player.status or "",
    } for player in slate.players]), width="stretch", hide_index=True)

st.subheader("Player decisions")
players = {p.platform_id: p for p in slate.players if p.platform_id in projection_by_id}
label = lambda pid: f"{players[pid].name} — {players[pid].team} {players[pid].primary_position.value}"
locked = []
if slate.contest_format == ContestFormat.CLASSIC:
    locked = st.multiselect("Lock players", tuple(players), format_func=label, key=f"build-locks-{hash(slate)}")
excluded = st.multiselect(
    "Exclude players", tuple(pid for pid in players if pid not in locked), format_func=label,
    key=f"build-exclusions-{hash(slate)}",
    help="Exclude inactive players, backups, and anyone you do not want in the portfolio.",
)
locked_ids, excluded_ids = frozenset(locked), frozenset(excluded)

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
if news:
    with st.expander(
        f"Review {len(news)} player-news item(s)",
        icon=":material/warning:",
        expanded=True,
    ):
        st.dataframe(pd.DataFrame(news, columns=("Type", "Player", "Team", "Details")), width="stretch", hide_index=True)

st.subheader("Portfolio")
if slate.contest_format == ContestFormat.CLASSIC:
    st.caption("Three-player uniqueness · 2/3 exposure cap · QB stack and bring-back · one ceiling lineup")
else:
    st.caption("Two-player uniqueness · 2/3 exposure cap · valid QB required · one ceiling lineup")

config_key = (
    st.session_state.get("projection_key"), st.session_state.get("ownership_hash"),
    hash(slate), tuple(sorted(locked_ids)), tuple(sorted(excluded_ids)), "3-max-v1",
)
st.session_state["current_config_key"] = config_key
if st.session_state.get("lineups") and st.session_state.get("lineup_config_key") != config_key:
    st.warning("Existing results are stale. Generate again before exporting.", icon=":material/update:")

if st.button("Generate three lineups", type="primary", icon=":material/bolt:", width="stretch"):
    try:
        matches = match_projections(slate, projections)
        with st.status("Optimizing portfolio…", expanded=True) as status:
            if slate.contest_format == ContestFormat.CLASSIC:
                lineups = generate_classic_3max_portfolio(
                    slate, matches,
                    ClassicOptimizationSettings(
                        locked_player_ids=locked_ids, excluded_player_ids=excluded_ids,
                        qb_stack_size=1, require_opponent_bring_back=True,
                        ceiling_weight=.3, minimum_stack_projection=7,
                        minimum_bring_back_projection=7, minimum_stack_ceiling=12,
                        minimum_bring_back_ceiling=12, unique_primary_stacks=True,
                    ),
                )
            else:
                lineups = generate_single_game_3max_portfolio(
                    slate, matches,
                    SingleGameOptimizationSettings(
                        multiplier_positions=frozenset({Position.QB, Position.RB, Position.WR, Position.TE}),
                        minimum_multiplier_ceiling=20, minimum_quarterbacks=1,
                        minimum_quarterback_projection=5, minimum_player_projection=.1,
                        maximum_players_per_team=4, maximum_kickers_and_defenses=1,
                        maximum_dst_opponents=1, require_multiplier_receiver_qb=True,
                        ceiling_weight=.3, excluded_player_ids=excluded_ids,
                    ),
                )
            status.update(label="Portfolio ready", state="complete", expanded=False)
        st.session_state["lineups"] = lineups
        st.session_state["lineup_config_key"] = config_key
        st.session_state["lineup_settings"] = {
            "portfolio_mode": "3-max tournament", "lineups": 3,
            "minimum_unique_players": 3 if slate.contest_format == ContestFormat.CLASSIC else 2,
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
