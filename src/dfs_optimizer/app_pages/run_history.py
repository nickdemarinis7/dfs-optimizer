from __future__ import annotations

import pandas as pd
import streamlit as st

from dfs_optimizer.app_state import restore_run_session
from dfs_optimizer.app_ui import (
    action_guide, apply_platform_theme, compact_file_uploader, hero, page_kicker,
)
from dfs_optimizer.services.run_history import (
    compare_runs,
    import_run_archive,
    list_run_records,
    mark_run_final,
    run_input_coverage,
    update_run_label,
)
from dfs_optimizer.services.run_replay import replay_run_archive


slate = st.session_state.get("slate")
if slate is not None:
    apply_platform_theme(slate.platform)

page_kicker(None, "Run history")
hero(
    "Your saved runs.",
    "Compare early-week and game-day portfolios while this browser session is active. Download important snapshots for permanent storage.",
)
action_guide(
    1,
    "Choose or import a saved run",
    "Open an earlier portfolio, import a downloaded run package, or mark the exact run you submitted as final.",
)

run_directory = st.session_state.get("run_directory", "data/runs")
with st.container(border=True):
    st.subheader("Import a run package")
    st.caption(
        "Use a complete run-package ZIP downloaded from this app. Its file hashes "
        "are verified before anything is restored."
    )
    with st.form("import-run-package", border=False):
        uploaded_run = compact_file_uploader(
            "Choose a run package",
            "Complete run package",
            type="zip",
            key="history-run-upload",
            help="Upload the dfs-run ZIP—not a contest standings ZIP.",
        )
        import_clicked = st.form_submit_button(
            "Import package",
            icon=":material/upload_file:",
            type="primary",
            width="stretch",
        )
    if import_clicked:
        if uploaded_run is None:
            st.warning("Choose a complete run-package ZIP first.")
        else:
            try:
                imported = import_run_archive(uploaded_run.getvalue(), run_directory)
            except (OSError, ValueError) as exc:
                st.error(f"Could not import this run package: {exc}")
            else:
                st.session_state["history-selected-run"] = imported.run_id
                st.session_state["run-imported-message"] = (
                    f"Imported {imported.label}. You can open it below."
                )
                st.rerun()

if message := st.session_state.pop("run-imported-message", None):
    st.success(message, icon=":material/verified:")

records = list_run_records(run_directory)
if not records:
    st.info("No locally saved runs yet. Your next lineup generation will appear here.")
    if st.button("Back to lineup builder", icon=":material/arrow_back:", width="stretch"):
        st.switch_page("app_pages/build.py")
    st.stop()

record_by_id = {item.run_id: item for item in records}
label = lambda run_id: (
    f"{'Final · ' if record_by_id[run_id].is_final else ''}"
    f"{record_by_id[run_id].label} · "
    f"{record_by_id[run_id].sport.value.upper()} · "
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
    coverage = run_input_coverage(selected)
    st.caption(
        "Inputs preserved · " + " · ".join(
            f"{'✓' if available else '—'} {name}"
            for name, available in coverage.items()
        )
    )

    new_label = st.text_input(
        "Label",
        value=selected.label,
        key=f"history-label-{selected.run_id}",
    )
    with st.container(horizontal=True, wrap=True):
        if st.button("Save label", icon=":material/save:"):
            update_run_label(selected.run_id, new_label, run_directory)
            st.rerun()
        if st.button("Mark as submitted", icon=":material/check_circle:", disabled=selected.is_final):
            mark_run_final(selected, run_directory)
            st.rerun()
    st.download_button(
        "Download snapshot",
        selected.path.read_bytes(),
        selected.path.name,
        "application/zip",
        icon=":material/download:",
        width="stretch",
    )
    if st.button(
        "Verify and replay archive",
        icon=":material/replay:",
        width="stretch",
        key=f"replay-{selected.run_id}",
    ):
        try:
            with st.spinner("Verifying hashes and rebuilding the run…"):
                replay_report = replay_run_archive(selected.path)
            st.session_state["archive_replay"] = (
                selected.run_id, replay_report
            )
        except (KeyError, OSError, ValueError) as exc:
            st.error(f"Could not inspect this archive: {exc}")
    replay_state = st.session_state.get("archive_replay")
    if replay_state and replay_state[0] == selected.run_id:
        report = replay_state[1]
        if not report.integrity_ok:
            st.error(
                "Archive integrity failed: " + "; ".join(report.integrity_errors),
                icon=":material/broken_image:",
            )
        elif not report.reconstructable:
            st.info(
                "Archive hashes are valid, but full replay is unavailable: "
                + (report.reason or "unsupported archive"),
                icon=":material/verified:",
            )
        else:
            replay_metrics = st.columns(4)
            replay_metrics[0].metric(
                "Model version",
                "Match" if report.model_version_match else "Changed",
            )
            replay_metrics[1].metric(
                "Projection changes", report.changed_projection_count
            )
            replay_metrics[2].metric(
                "Maximum delta", f"{report.maximum_projection_delta:.3f}"
            )
            replay_metrics[3].metric(
                "Exact lineups",
                f"{report.exact_lineup_matches}/{report.archived_lineup_count}",
            )
            if report.changed_confidence_count:
                st.caption(
                    f"Confidence changed for {report.changed_confidence_count} players · "
                    f"maximum score delta {report.maximum_confidence_delta:.1f}"
                )
            if (
                report.integrity_ok and report.model_version_match
                and report.projections_match and report.lineups_match
            ):
                st.success(
                    "The archive is intact and the projections and lineups reproduced exactly.",
                    icon=":material/verified:",
                )
            else:
                details = []
                if not report.model_version_match:
                    details.append(
                        f"model {report.archived_model_version or 'unknown'} → "
                        f"{report.current_model_version or 'unknown'}"
                    )
                if report.missing_projection_ids:
                    details.append(
                        f"{len(report.missing_projection_ids)} archived players missing"
                    )
                if report.unexpected_projection_ids:
                    details.append(
                        f"{len(report.unexpected_projection_ids)} new players"
                    )
                st.warning(
                    "Replay drift detected" + (": " + "; ".join(details) if details else "."),
                    icon=":material/change_circle:",
                )
    if st.button("Open this run", icon=":material/restore:", width="stretch"):
        try:
            restore_run_session(st.session_state, selected)
        except (KeyError, OSError, ValueError) as exc:
            st.error(f"Could not restore this run: {exc}")
        else:
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
    if comparison.context_changes:
        st.caption("Weekly context changes")
        st.dataframe(
            pd.DataFrame(comparison.context_changes),
            hide_index=True,
            width="stretch",
        )

if st.button("Back to results", icon=":material/arrow_back:", width="stretch"):
    st.switch_page("app_pages/results.py")
