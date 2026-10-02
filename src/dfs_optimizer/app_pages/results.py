from __future__ import annotations

from collections import Counter

import pandas as pd
import streamlit as st

from dfs_optimizer.app_ui import apply_platform_theme, hero, page_kicker
from dfs_optimizer.exporters import lineups_csv_text, merge_lineups_into_template
from dfs_optimizer.services.portfolio import analyze_portfolio
from dfs_optimizer.services.preflight import preflight_lineups
from dfs_optimizer.services.run_archive import build_run_archive


slate = st.session_state.get("slate")
projections = st.session_state.get("projections", ())
lineups = st.session_state.get("lineups", ())
if slate is not None:
    apply_platform_theme(slate.platform)
page_kicker(3, "Review")
hero("Your portfolio.", "Move between lineups, inspect the tradeoffs, and export when everything looks right.")
if slate is None or not projections or not lineups:
    st.warning("Generate a portfolio on the Build lineups screen first.", icon=":material/arrow_back:")
    st.stop()

diagnostics = analyze_portfolio(lineups, len(projections), len(slate.players))
report = preflight_lineups(
    slate,
    projections,
    lineups,
    expected_lineups=int(st.session_state.get("lineup_settings", {}).get("lineups", 3)),
    projection_built_at=st.session_state.get("projection_built_at"),
)
audit = report.findings
stale = (
    st.session_state.get("current_config_key") is not None
    and st.session_state.get("lineup_config_key") != st.session_state.get("current_config_key")
)
blocking = stale or report.blocking
if stale:
    st.warning(
        "These results are stale because player decisions changed. Regenerate before exporting.",
        icon=":material/update:",
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
    top_metrics = st.columns(2)
    top_metrics[0].metric("Median", f"{lineup.projected_points:.2f}")
    top_metrics[1].metric("Ceiling", f"{ceiling:.2f}")
    bottom_metrics = st.columns(2)
    bottom_metrics[0].metric("Salary", f"${lineup.salary:,}")
    bottom_metrics[1].metric("Unused", f"${lineup.salary_cap - lineup.salary:,}")
    st.dataframe(pd.DataFrame([{
        "Slot": entry.slot,
        "Player": entry.player.name,
        "Team": entry.player.team,
        "Projection": entry.projection.projected_points
        * getattr(entry, "point_multiplier", 1),
        "Status": entry.player.status or "",
    } for entry in lineup.entries]), width="stretch", hide_index=True)

with st.expander("Portfolio exposure", icon=":material/donut_large:"):
    for warning in diagnostics.warnings:
        st.warning(warning)
    counts = Counter(e.player.name for lineup in lineups for e in lineup.entries)
    st.dataframe(pd.DataFrame([{"Player": name, "Appearances": count, "Exposure": 100 * count / len(lineups)} for name, count in counts.most_common()]), width="stretch", hide_index=True)

with st.expander("Pre-submit audit", icon=":material/fact_check:", expanded=blocking):
    if audit:
        st.dataframe(pd.DataFrame([{"Severity": x.severity, "Check": x.code, "Details": x.message} for x in audit]), width="stretch", hide_index=True)
    else:
        st.success("No pre-submit audit findings.")

with st.expander("Download entries", icon=":material/download:", expanded=True):
    st.download_button("Download lineup CSV", lineups_csv_text(lineups, slate.platform).encode(), "lineups.csv", "text/csv", disabled=blocking, icon=":material/download:", width="stretch")
    template = st.file_uploader("Official contest-entry template (optional)", type="csv")
    if template:
        try:
            completed = merge_lineups_into_template(lineups, slate.platform, template.getvalue())
            st.download_button("Download completed entry template", completed, "completed-entry-template.csv", "text/csv", disabled=blocking, icon=":material/download:", width="stretch")
        except (UnicodeError, ValueError) as exc:
            st.error(str(exc))
    st.download_button("Download run archive", build_run_archive(slate, projections, lineups, st.session_state.get("lineup_settings", {})), "dfs-run.zip", "application/zip", disabled=blocking, icon=":material/archive:", width="stretch")

if st.button("Back to player review", icon=":material/arrow_back:", width="stretch"):
    st.switch_page("app_pages/build.py")
