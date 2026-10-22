from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib

import pandas as pd
import streamlit as st

from dfs_optimizer.app_ui import (
    action_guide,
    apply_platform_theme,
    hero,
    optional_label,
    page_kicker,
    section_intro,
)
from dfs_optimizer.exporters import lineups_csv_text, merge_lineups_into_template
from dfs_optimizer.models import ContestFormat, Position, Sport
from dfs_optimizer.services.portfolio import analyze_portfolio
from dfs_optimizer.services.preflight import preflight_lineups
from dfs_optimizer.services.run_archive import build_run_archive
from dfs_optimizer.services.scenarios import simulate_lineups
from dfs_optimizer.services.submissions import (
    compare_submitted_rosters,
    import_submitted_rosters,
    save_submission_snapshot,
    submission_snapshot_bytes,
)


def _lineup_story(lineup, contest_format: ContestFormat) -> str:
    """Describe the lineup construction in plain language."""
    if contest_format == ContestFormat.CLASSIC:
        quarterback = next(
            (
                entry.player
                for entry in lineup.entries
                if entry.player.primary_position == Position.QB
            ),
            None,
        )
        parts = []
        if quarterback is not None:
            partners = [
                entry.player.name
                for entry in lineup.entries
                if entry.player.team == quarterback.team
                and entry.player.primary_position in {Position.WR, Position.TE}
            ]
            bring_backs = [
                entry.player.name
                for entry in lineup.entries
                if entry.player.team == quarterback.opponent
                and entry.player.primary_position in {Position.RB, Position.WR, Position.TE}
            ]
            if partners:
                parts.append(f"{quarterback.name} paired with {', '.join(partners)}")
            if bring_backs:
                parts.append(f"bring-back: {', '.join(bring_backs)}")
        tight_ends = [
            entry.player.name
            for entry in lineup.entries
            if entry.player.primary_position == Position.TE
        ]
        if len(tight_ends) > 1:
            parts.append(f"two-TE build: {', '.join(tight_ends)}")
        return " · ".join(parts) or "Balanced projection-first construction"

    multiplier = next(
        (
            entry
            for entry in lineup.entries
            if not entry.slot.upper().startswith("FLEX")
        ),
        lineup.entries[0],
    )
    team_counts = Counter(entry.player.team for entry in lineup.entries)
    split = "–".join(str(count) for _, count in team_counts.most_common())
    return f"{multiplier.slot}: {multiplier.player.name} · {split} team split"


slate = st.session_state.get("slate")
projections = st.session_state.get("projections", ())
lineups = st.session_state.get("lineups", ())
if slate is not None:
    apply_platform_theme(slate.platform)
page_kicker(3, "Review")
hero("Portfolio ready.", "Review the construction and risk, then download the entry file for your contest site.")
if slate is None or not projections or not lineups:
    st.warning("Generate a portfolio on the Build lineups screen first.", icon=":material/arrow_back:")
    st.stop()

if st.session_state.get("generation_warning"):
    st.warning(st.session_state["generation_warning"], icon=":material/info:")

diagnostics = analyze_portfolio(lineups, len(projections), len(slate.players))
report = preflight_lineups(
    slate,
    projections,
    lineups,
    expected_lineups=int(st.session_state.get("lineup_settings", {}).get("lineups", 3)),
    projection_built_at=st.session_state.get("projection_built_at"),
    salary_loaded_at=st.session_state.get("salary_loaded_at"),
    player_context=tuple(st.session_state.get("player_context", ())),
    player_context_built_at=st.session_state.get("player_context_built_at"),
    prop_checked_at=st.session_state.get("nfl_prop_checked_at"),
    prop_players_matched=sum(
        bool(item.prop_market_count) for item in projections
    ),
)
selected_player_ids = {
    entry.player.platform_id for lineup in lineups for entry in lineup.entries
    if entry.player.primary_position != Position.DST
}
final_status_ids = {
    item.platform_id
    for item in st.session_state.get("final_status_context", ())
}
if final_status_ids:
    confirmed_selected = len(selected_player_ids & final_status_ids)
    st.caption(
        f"Final-status coverage · {confirmed_selected} of "
        f"{len(selected_player_ids)} selected players confirmed"
    )
audit = report.findings
stale = (
    st.session_state.get("current_config_key") is not None
    and st.session_state.get("lineup_config_key") != st.session_state.get("current_config_key")
)
cfb_confirmation_stale = False
if slate.sport == Sport.CFB:
    confirmed_value = st.session_state.get("lineup_settings", {}).get(
        "cfb_final_status_confirmed_at"
    )
    try:
        confirmed_at = datetime.fromisoformat(confirmed_value)
        if confirmed_at.tzinfo is None:
            confirmed_at = confirmed_at.replace(tzinfo=timezone.utc)
        cfb_confirmation_stale = (
            datetime.now(timezone.utc) - confirmed_at
        ).total_seconds() > 30 * 60
    except (TypeError, ValueError):
        cfb_confirmation_stale = True
blocking = stale or cfb_confirmation_stale or report.blocking
if stale:
    st.warning(
        "These results are stale because player decisions changed. Regenerate before exporting.",
        icon=":material/update:",
    )
if cfb_confirmation_stale:
    st.warning(
        "The CFB availability confirmation is missing or more than 30 minutes old. "
        "Return to Build, recheck final statuses and quarterbacks, then regenerate.",
        icon=":material/update:",
    )
if blocking:
    st.error(
        "Action required before download. Review the pre-submit findings below.",
        icon=":material/report:",
    )
else:
    st.success(
        f"Ready to submit · {len(lineups)} lineup{'s' if len(lineups) != 1 else ''} passed the blocking checks.",
        icon=":material/verified:",
    )
action_guide(
    1,
    "Review every lineup",
    "Tap the lineup numbers below and confirm the players, salary, and any warnings before downloading.",
)
selected_number = st.segmented_control(
    "Lineup",
    tuple(range(1, len(lineups) + 1)),
    default=1,
    format_func=lambda number: (
        "Ceiling"
        if number == st.session_state.get("lineup_settings", {}).get("ceiling_lineup_number")
        else f"Lineup {number}"
    ),
    width="stretch",
)
lineup = lineups[selected_number - 1]
scenario_analysis = st.session_state.get("scenario_analysis", ())
if len(scenario_analysis) != len(lineups):
    scenario_analysis = simulate_lineups(lineups)
    st.session_state["scenario_analysis"] = scenario_analysis
lineup_scenario = scenario_analysis[selected_number - 1]
role = (
    "Ceiling"
    if selected_number == st.session_state.get("lineup_settings", {}).get("ceiling_lineup_number")
    else f"Lineup {selected_number}"
)
ceiling = sum(
    (entry.projection.ceiling or entry.projection.projected_points)
    * getattr(entry, "point_multiplier", 1)
    for entry in lineup.entries
)
with st.container(border=True):
    st.subheader(role)
    st.badge(lineup_scenario.label, color="violet")
    st.markdown(
        f"**Construction** · {_lineup_story(lineup, slate.contest_format)}"
    )
    top_metrics = st.columns(3)
    top_metrics[0].metric("Median", f"{lineup.projected_points:.2f}")
    top_metrics[1].metric("P90", f"{lineup_scenario.p90:.2f}")
    top_metrics[2].metric("Ceiling", f"{ceiling:.2f}")
    bottom_metrics = st.columns(3)
    bottom_metrics[0].metric("Salary", f"${lineup.salary:,}")
    bottom_metrics[1].metric("Unused", f"${lineup.salary_cap - lineup.salary:,}")
    bottom_metrics[2].metric(
        "Portfolio-best rate", f"{lineup_scenario.top_rate:.1%}",
        help=(
            "How often this lineup scores highest among only the lineups in "
            "this generated portfolio. It is not a contest win probability."
        ),
    )
    st.dataframe(pd.DataFrame([{
        "Slot": entry.slot,
        "Player": entry.player.name,
        "Team": entry.player.team,
        "Projection": entry.projection.projected_points
        * getattr(entry, "point_multiplier", 1),
        "Status": entry.player.status or "—",
    } for entry in lineup.entries]),
        column_config={
            "Projection": st.column_config.NumberColumn(format="%.1f"),
        },
        width="stretch", hide_index=True,
    )

with st.container(border=True):
    section_intro(
        "Pre-submit check",
        "Resolve any blocking issue before downloading. Informational notes do not prevent export.",
        icon=":material/fact_check:",
    )
    if audit:
        for finding in audit:
            message = f"**{finding.code.replace('_', ' ').title()}**  \n{finding.message}"
            if finding.severity == "ERROR":
                st.error(message, icon=":material/error:")
            else:
                st.warning(message, icon=":material/warning:")
    else:
        st.success("No pre-submit audit findings.", icon=":material/verified:")

action_guide(
    2,
    "Download and submit",
    "Download the lineup CSV below, then upload it on DraftKings or FanDuel. A blocking warning disables downloads until it is fixed.",
)
with st.container(border=True):
    section_intro(
        "Entry files",
        "The basic CSV lists your lineups. The official-template option is best when the contest site provides an entry-edit file.",
        icon=":material/download:",
    )
    st.download_button(
        "Download lineup CSV",
        lineups_csv_text(lineups, slate.platform).encode(),
        "lineups.csv",
        "text/csv",
        disabled=blocking,
        icon=":material/download:",
        type="primary",
        width="stretch",
    )
    template = st.file_uploader("Official contest-entry template (optional)", type="csv")
    if template:
        try:
            completed = merge_lineups_into_template(lineups, slate.platform, template.getvalue())
            st.download_button("Download completed entry template", completed, "completed-entry-template.csv", "text/csv", disabled=blocking, icon=":material/download:", width="stretch")
        except (UnicodeError, ValueError) as exc:
            st.error(str(exc))
    archive = st.session_state.get("run_archive")
    if archive is None:
        archive = build_run_archive(
            slate,
            projections,
            lineups,
            st.session_state.get("lineup_settings", {}),
            salary_content=st.session_state.get("salary_content"),
        )
    st.download_button(
        "Download complete run package",
        archive,
        st.session_state.get("run_archive_name") or "dfs-run.zip",
        "application/zip",
        disabled=blocking,
        icon=":material/archive:",
        width="stretch",
    )
    saved_run_path = st.session_state.get("saved_run_path")
    if saved_run_path:
        st.caption(
            "This run is available in Run history for the current browser session. "
            "Download the complete run package for durable storage."
        )

optional_label("Optional portfolio analysis")
exposure_tab, simulation_tab = st.tabs([
    ":material/donut_large: Exposure",
    ":material/casino: Simulations",
])
with exposure_tab:
    st.caption(
        "Exposure shows how often each player appears across your entries. "
        "High exposure means more risk is concentrated in that player."
    )
    for warning in diagnostics.warnings:
        st.warning(warning)
    counts = Counter(e.player.name for lineup in lineups for e in lineup.entries)
    st.dataframe(
        pd.DataFrame([
            {
                "Player": name,
                "Appearances": count,
                "Exposure": 100 * count / len(lineups),
            }
            for name, count in counts.most_common()
        ]),
        width="stretch",
        hide_index=True,
    )
with simulation_tab:
    st.caption(
        "Two thousand correlated simulations estimate upside and how often each "
        "lineup leads only this generated portfolio. These rates are not full-field "
        "contest win probabilities."
    )
    st.dataframe(
        pd.DataFrame([
            {
                "Lineup": item.lineup_number,
                "Game script": item.label,
                "Mean": item.mean,
                "P75": item.p75,
                "P90": item.p90,
                "Portfolio-best rate": item.top_rate,
            }
            for item in scenario_analysis
        ]),
        column_config={
            "Mean": st.column_config.NumberColumn(format="%.2f"),
            "P75": st.column_config.NumberColumn(format="%.2f"),
            "P90": st.column_config.NumberColumn(format="%.2f"),
            "Portfolio-best rate": st.column_config.NumberColumn(
                format="percent",
                help="Best within this generated portfolio, not the full contest field.",
            ),
        },
        hide_index=True,
        width="stretch",
    )

action_guide(
    3,
    "Save what you actually entered",
    "After submitting on the contest site, upload the completed entry CSV here so later results are matched to the real rosters.",
)
with st.container(border=True):
    section_intro(
        "Final submission record",
        "This is optional but recommended. It preserves what you actually entered, including any last-minute swaps made on the contest site.",
        icon=":material/verified:",
    )
    st.caption(
        "After uploading entries to the platform, add that completed CSV here. "
        "This becomes the pre-lock source of truth and is compared with this generated run."
    )
    submitted_file = st.file_uploader(
        "Completed platform entry CSV",
        type="csv",
        key="final-submission-file",
    )
    if submitted_file is not None:
        try:
            submitted_content = submitted_file.getvalue()
            submitted_rosters = import_submitted_rosters(submitted_content, slate)
            submission_comparison = compare_submitted_rosters(submitted_rosters, lineups)
            content_hash = hashlib.sha256(submitted_content).hexdigest()
            run_id = st.session_state.get("current_run_id") or f"submission-{content_hash[:12]}"
            snapshot_key = (run_id, content_hash)
            if st.session_state.get("submission_snapshot_key") != snapshot_key:
                snapshot = submission_snapshot_bytes(
                    run_id, slate, submitted_rosters, submission_comparison
                )
                saved_submission_path = None
                try:
                    saved_submission_path = save_submission_snapshot(snapshot, run_id)
                except OSError:
                    pass
                st.session_state["submission_snapshot_key"] = snapshot_key
                st.session_state["submission_snapshot"] = snapshot
                st.session_state["saved_submission_path"] = (
                    str(saved_submission_path) if saved_submission_path else None
                )
            comparison_metrics = st.columns(3)
            comparison_metrics[0].metric("Submitted", submission_comparison.submitted_count)
            comparison_metrics[1].metric("Exact matches", submission_comparison.exact_matches)
            comparison_metrics[2].metric("Changed", submission_comparison.changed_count)
            st.dataframe(
                pd.DataFrame([
                    {"Entry": roster.lineup_number, "Final roster": roster.display}
                    for roster in submitted_rosters
                ]),
                hide_index=True,
                width="stretch",
            )
            if submission_comparison.changed_count:
                st.warning(
                    "The final submission differs from the generated portfolio. "
                    "The captured snapshot will be used as the authoritative pre-lock record."
                )
            else:
                st.success("The final submission exactly matches the generated portfolio.")
            st.download_button(
                "Download submission snapshot",
                st.session_state["submission_snapshot"],
                f"{run_id}-submission.json",
                "application/json",
                icon=":material/download:",
                width="stretch",
            )
        except (UnicodeError, ValueError) as exc:
            st.error(str(exc))

optional_label("After the contest")
if st.button("Review contest results", icon=":material/history:", width="stretch"):
    st.switch_page("app_pages/backtest.py")

if st.button("View run history", icon=":material/history_toggle_off:", width="stretch"):
    st.switch_page("app_pages/run_history.py")

if st.button("Back to player review", icon=":material/arrow_back:", width="stretch"):
    st.switch_page("app_pages/build.py")
