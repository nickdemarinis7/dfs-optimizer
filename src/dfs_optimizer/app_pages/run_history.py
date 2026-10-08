from __future__ import annotations

import pandas as pd
import streamlit as st

from dfs_optimizer.app_ui import apply_platform_theme, hero
from dfs_optimizer.services import (
    compare_runs,
    list_run_records,
    mark_run_final,
    restore_run,
    update_run_label,
)


slate = st.session_state.get("slate")
if slate is not None:
    apply_platform_theme(slate.platform)

hero(
    "Every run, preserved.",
    "Compare early-week and game-day portfolios, reopen any snapshot, and mark the one you actually submitted.",
)

records = list_run_records()
if not records:
    st.info("No locally saved runs yet. Your next lineup generation will appear here.")
    if st.button("Back to lineup builder", icon=":material/arrow_back:", width="stretch"):
        st.switch_page("app_pages/build.py")
    st.stop()

record_by_id = {item.run_id: item for item in records}
label = lambda run_id: (
    f"{'Final · ' if record_by_id[run_id].is_final else ''}"
    f"{record_by_id[run_id].label} · "
    f"{record_by_id[run_id].platform.value.title()} "
    f"{record_by_id[run_id].contest_format.value.replace('_', ' ').title()}"
)

selected_id = st.selectbox(
    "Saved run",
    tuple(record_by_id),
    format_func=label,
    key="history-selected-run",
)
selected = record_by_id[selected_id]
with st.container(border=True):
    st.subheader(selected.label)
    st.caption(selected.created_at.astimezone().strftime("%A, %B %-d at %-I:%M %p %Z"))
    facts = st.columns(3)
    facts[0].metric("Lineups", selected.lineup_count)
    facts[1].metric("Players", selected.projection_count)
    facts[2].metric("Status", "Final" if selected.is_final else "Draft")
    st.caption(f"Salary source: `{selected.source_name}`")

    new_label = st.text_input(
        "Label",
        value=selected.label,
        key=f"history-label-{selected.run_id}",
    )
    with st.container(horizontal=True, wrap=True):
        if st.button("Save label", icon=":material/save:"):
            update_run_label(selected.run_id, new_label)
            st.rerun()
        if st.button("Mark as submitted", icon=":material/check_circle:", disabled=selected.is_final):
            mark_run_final(selected)
            st.rerun()
    st.download_button(
        "Download snapshot",
        selected.path.read_bytes(),
        selected.path.name,
        "application/zip",
        icon=":material/download:",
        width="stretch",
    )
    if st.button("Open this run", icon=":material/restore:", width="stretch"):
        try:
            loaded_slate, projections, lineups, salary_content, settings = restore_run(selected)
        except (KeyError, OSError, ValueError) as exc:
            st.error(f"Could not restore this run: {exc}")
        else:
            st.session_state["slate"] = loaded_slate
            st.session_state["source_name"] = loaded_slate.source_name
            st.session_state["salary_content"] = salary_content
            st.session_state["projections"] = projections
            st.session_state["lineups"] = lineups
            st.session_state["lineup_settings"] = settings
            st.session_state["run_archive"] = selected.path.read_bytes()
            st.session_state["run_archive_name"] = selected.path.name
            st.session_state["saved_run_path"] = str(selected.path)
            st.session_state["current_run_id"] = selected.run_id
            st.session_state["lineup_config_key"] = None
            st.session_state["current_config_key"] = None
            st.switch_page("app_pages/results.py")

if len(records) > 1:
    st.subheader("Compare runs")
    comparison_ids = tuple(item.run_id for item in records if item.run_id != selected_id)
    comparison_id = st.selectbox(
        "Compare selected run with",
        comparison_ids,
        format_func=label,
        key="history-comparison-run",
    )
    other = record_by_id[comparison_id]
    if selected.slate_id != other.slate_id:
        st.warning("These runs appear to be from different slates. Comparisons may not be meaningful.")
    earlier, later = sorted((selected, other), key=lambda item: item.created_at)
    comparison = compare_runs(earlier, later)
    metrics = st.columns(3)
    metrics[0].metric("Material changes", comparison.material_projection_count)
    metrics[1].metric("Lineup overlap", f"{comparison.lineup_overlap_percent:.0f}%")
    metrics[2].metric("Identical lineups", comparison.shared_lineups)
    if comparison.projection_changes:
        st.dataframe(
            pd.DataFrame(comparison.projection_changes),
            column_config={
                "Earlier": st.column_config.NumberColumn(format="%.2f"),
                "Later": st.column_config.NumberColumn(format="%.2f"),
                "Change": st.column_config.NumberColumn(format="%+.2f"),
            },
            hide_index=True,
            width="stretch",
        )
    else:
        st.success("The projection snapshots are identical.")

if st.button("Back to results", icon=":material/arrow_back:", width="stretch"):
    st.switch_page("app_pages/results.py")
