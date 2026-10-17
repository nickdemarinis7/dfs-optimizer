from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import streamlit as st

from dfs_optimizer.app_ui import action_guide, apply_platform_theme, hero, page_kicker
from dfs_optimizer.backtesting import (
    evaluate_projection_rows,
    evaluate_projections,
    import_player_results_content,
)
from dfs_optimizer.services.results_review import (
    CapturedSubmission,
    SavedPortfolio,
    classify_submitted_entry_provenance,
    extract_submitted_entries,
    review_contest_results,
)
from dfs_optimizer.services.run_history import list_run_records, restore_run
from dfs_optimizer.services.submissions import load_submission_snapshot
from dfs_optimizer.services.calibration import (
    calibration_record,
    calibration_record_bytes,
    list_calibration_records,
    save_calibration_record,
)


slate = st.session_state.get("slate")
lineups = st.session_state.get("lineups", ())
projections = st.session_state.get("projections", ())
if slate is not None:
    apply_platform_theme(slate.platform)

page_kicker(None, "Backtest")
hero(
    "Grade the slate.",
    "Upload the final standings to measure lineup performance and projection accuracy against what actually happened.",
)
action_guide(
    1,
    "Upload the final contest standings",
    "Use this only after scoring is complete. Export the standings from your contest site and add your username for the most reliable match.",
)

if slate is None or not lineups:
    st.warning("Generate lineups before reviewing contest results.", icon=":material/arrow_back:")
    if st.button("Back to lineup builder", icon=":material/arrow_back:", width="stretch"):
        st.switch_page("app_pages/build.py")
    st.stop()

st.caption(
    f"{slate.platform.value.title()} · {slate.contest_format.value.replace('_', ' ').title()} · "
    f"{len(lineups)} generated lineups"
)
results_file = st.file_uploader(
    "Contest standings",
    type=("csv", "zip"),
    help="Use the final contest standings export from DraftKings or FanDuel.",
)
entry_filter = st.text_input(
    "Your username (recommended)",
    placeholder="Your username",
    help="Use this when an identical lineup appears more than once with different scores.",
)

if results_file is not None:
    try:
        review = review_contest_results(
            results_file.getvalue(),
            results_file.name,
            lineups,
            slate.platform,
            slate.contest_format,
            entry_filter,
        )
    except ValueError as exc:
        st.error(str(exc), icon=":material/error:")
    else:
        submitted = ()
        metrics = st.columns(3)
        metrics[0].metric("Field", f"{review.field_size:,}")
        metrics[1].metric("Winning score", f"{review.winning_score:.2f}")
        metrics[2].metric("Matched", f"{len(review.lineups)}/{len(lineups)}")

        if entry_filter.strip():
            submitted = extract_submitted_entries(
                results_file.getvalue(),
                results_file.name,
                slate.platform,
                slate.contest_format,
                entry_filter,
            )
            current_run_id = st.session_state.get("current_run_id")
            portfolios = [SavedPortfolio(
                run_id=current_run_id or "current-session",
                label="Current session run",
                lineups=tuple(lineups),
                is_current=True,
            )]
            saved_runs = list_run_records()
            current_record = next(
                (record for record in saved_runs if record.run_id == current_run_id),
                None,
            )
            if current_record is not None:
                for record_item in saved_runs:
                    if (
                        record_item.run_id == current_record.run_id
                        or record_item.slate_id != current_record.slate_id
                    ):
                        continue
                    try:
                        _, _, saved_lineups, _, _ = restore_run(record_item)
                    except (KeyError, OSError, ValueError):
                        continue
                    portfolios.append(SavedPortfolio(
                        run_id=record_item.run_id,
                        label=record_item.label,
                        lineups=saved_lineups,
                    ))
            captured_submissions = []
            snapshot_path_value = st.session_state.get("saved_submission_path")
            snapshot_path = (
                Path(snapshot_path_value)
                if snapshot_path_value
                else Path("data/submissions") / f"{current_run_id}.json"
                if current_run_id else None
            )
            if snapshot_path is not None and snapshot_path.is_file():
                try:
                    snapshot = load_submission_snapshot(snapshot_path)
                except ValueError:
                    pass
                else:
                    if (
                        snapshot.run_id == current_run_id
                        and snapshot.platform == slate.platform
                        and snapshot.contest_format == slate.contest_format
                    ):
                        captured_submissions.append(CapturedSubmission(
                            run_id=snapshot.run_id,
                            label="Captured final submission",
                            rosters=snapshot.rosters,
                        ))
            provenance = classify_submitted_entry_provenance(
                submitted,
                tuple(portfolios),
                slate.platform,
                slate.contest_format,
                tuple(captured_submissions),
            )
            st.subheader("Actual submitted entries")
            if submitted:
                st.dataframe(
                    pd.DataFrame([
                        {
                            "Source": item.source,
                            "Run": item.run_label or "Not matched to a saved run",
                            "Rank": item.entry.rank,
                            "Score": item.entry.score,
                            "Top %": round(100 * item.entry.rank / review.field_size, 2),
                            "Duplicates": item.entry.duplication,
                            "Lineup": ", ".join(
                                f"{role} {name}".strip()
                                for role, name in item.entry.lineup
                            ),
                        }
                        for item in provenance
                    ]),
                    hide_index=True,
                    width="stretch",
                )
                unverified_count = sum(not item.verified for item in provenance)
                earlier_count = sum(item.source == "Earlier saved run" for item in provenance)
                captured_count = sum(
                    item.source == "Captured submission change" for item in provenance
                )
                if unverified_count:
                    st.warning(
                        f"{unverified_count} submitted entr{'y was' if unverified_count == 1 else 'ies were'} "
                        "not found in a saved app run. They are shown for context but excluded "
                        "from this run's performance record.",
                        icon=":material/fact_check:",
                    )
                if earlier_count:
                    st.info(
                        f"{earlier_count} submitted entr{'y matches' if earlier_count == 1 else 'ies match'} "
                        "an earlier saved run and are labeled separately from the current portfolio."
                    )
                if captured_count:
                    st.info(
                        f"{captured_count} submitted entr{'y matches' if captured_count == 1 else 'ies match'} "
                        "the saved final-submission record but not the generated portfolio. "
                        "They are documented manual changes and are excluded from optimizer validation."
                    )
            else:
                st.warning("No scored entries matched that username.")

        st.subheader("Saved-run matches")
        if review.lineups:
            st.dataframe(
                pd.DataFrame([
                    {
                        "Lineup": item.lineup_number,
                        "Score": item.score,
                        "Rank": item.rank,
                        "Top %": round(item.top_percent, 2),
                        "Duplicates": item.duplication,
                        "Entry": item.entry_name,
                    }
                    for item in review.lineups
                ]),
                hide_index=True,
                width="stretch",
            )
        if review.unmatched_lineups:
            numbers = ", ".join(map(str, review.unmatched_lineups))
            st.warning(f"Could not find generated lineup(s): {numbers}.")
        if review.ambiguous_lineups:
            numbers = ", ".join(map(str, review.ambiguous_lineups))
            st.warning(
                f"Lineup(s) {numbers} matched entries with different scores. Add your username above to identify yours."
            )

        st.subheader("Projection evaluation")
        try:
            actuals = import_player_results_content(
                results_file.getvalue(),
                results_file.name,
                {player.name: player.primary_position.value for player in slate.players},
            )
            projection_metrics = evaluate_projections(tuple(projections), actuals)
            evaluation_rows = evaluate_projection_rows(tuple(projections), actuals)
        except ValueError as exc:
            st.info(f"Player-level evaluation is unavailable: {exc}")
        else:
            metric_columns = st.columns(3)
            metric_columns[0].metric("Players matched", projection_metrics.matched_players)
            metric_columns[1].metric("MAE", f"{projection_metrics.mean_absolute_error:.2f}")
            metric_columns[2].metric("Bias", f"{projection_metrics.mean_error:+.2f}")
            calibration_columns = st.columns(3)
            calibration_columns[0].metric("RMSE", f"{projection_metrics.root_mean_squared_error:.2f}")
            calibration_columns[1].metric(
                "Correlation",
                f"{projection_metrics.correlation:.2f}"
                if projection_metrics.correlation is not None else "—",
            )
            calibration_columns[2].metric(
                "Range coverage",
                f"{projection_metrics.interval_coverage:.0%}"
                if projection_metrics.interval_coverage is not None else "—",
            )
            evaluation_frame = pd.DataFrame([
                {
                    "Player": row.name,
                    "Pos": row.position,
                    "Projected": row.projected,
                    "Actual": row.actual,
                    "Error": row.error,
                    "Absolute error": row.absolute_error,
                }
                for row in evaluation_rows
            ])
            position_frame = (
                evaluation_frame.groupby("Pos", as_index=False)
                .agg(
                    Players=("Player", "count"),
                    MAE=("Absolute error", "mean"),
                    Bias=("Error", "mean"),
                )
                .sort_values("MAE", ascending=False)
            )
            st.caption("Error by position")
            st.dataframe(
                position_frame,
                column_config={
                    "MAE": st.column_config.NumberColumn(format="%.2f"),
                    "Bias": st.column_config.NumberColumn(format="%+.2f"),
                },
                hide_index=True,
                width="stretch",
            )
            st.caption("Largest player misses")
            st.dataframe(
                evaluation_frame.sort_values("Absolute error", ascending=False),
                column_config={
                    column: st.column_config.NumberColumn(format="%.2f")
                    for column in ("Projected", "Actual", "Error", "Absolute error")
                },
                hide_index=True,
                width="stretch",
            )
            if projection_metrics.ownership_samples:
                st.caption("Ownership calibration")
                with st.container(horizontal=True):
                    st.metric(
                        "Players matched",
                        projection_metrics.ownership_samples,
                        border=True,
                    )
                    st.metric(
                        "Ownership MAE",
                        f"{projection_metrics.ownership_mean_absolute_error:.2f}%",
                        border=True,
                    )
                    st.metric(
                        "Ownership bias",
                        f"{projection_metrics.ownership_mean_error:+.2f}%",
                        border=True,
                    )
                    st.metric(
                        "Ownership correlation",
                        (
                            f"{projection_metrics.ownership_correlation:.2f}"
                            if projection_metrics.ownership_correlation is not None
                            else "—"
                        ),
                        border=True,
                    )
                ownership_frame = pd.DataFrame([
                    {
                        "Player": row.name,
                        "Pos": row.position,
                        "Projected ownership": row.projected_ownership,
                        "Actual ownership": row.actual_ownership,
                        "Ownership error": row.projected_ownership - row.actual_ownership,
                    }
                    for row in evaluation_rows
                    if row.projected_ownership is not None
                    and row.actual_ownership is not None
                ]).sort_values(
                    "Ownership error", key=lambda values: values.abs(), ascending=False
                )
                st.dataframe(
                    ownership_frame,
                    column_config={
                        column: st.column_config.NumberColumn(format="%.2f%%")
                        for column in (
                            "Projected ownership", "Actual ownership", "Ownership error"
                        )
                    },
                    hide_index=True,
                    width="stretch",
                )
            result_hash = hashlib.sha256(results_file.getvalue()).hexdigest()
            run_id = st.session_state.get("current_run_id") or f"results-{result_hash[:12]}"
            verified_current_entries = tuple(
                item.entry for item in provenance if item.current_run
            ) if entry_filter.strip() else ()
            record = calibration_record(
                run_id,
                slate,
                projection_metrics,
                evaluation_rows,
                review.field_size,
                review.winning_score,
                verified_current_entries,
            )
            record_key = (run_id, result_hash, entry_filter.strip().casefold())
            if st.session_state.get("calibration_record_key") != record_key:
                saved_calibration_path = None
                try:
                    saved_calibration_path = save_calibration_record(record)
                except OSError:
                    pass
                st.session_state["calibration_record_key"] = record_key
                st.session_state["calibration_record"] = record
                st.session_state["saved_calibration_path"] = (
                    str(saved_calibration_path) if saved_calibration_path else None
                )
            st.download_button(
                "Download calibration record",
                calibration_record_bytes(st.session_state["calibration_record"]),
                f"{run_id}-calibration.json",
                "application/json",
                icon=":material/download:",
                width="stretch",
            )

records = list_calibration_records()
if records:
    with st.expander("Calibration history", icon=":material/monitoring:"):
        history = pd.DataFrame([
            {
                "Run": item["run_id"],
                "Platform": item["platform"],
                "Format": item["contest_format"].replace("_", " ").title(),
                "Players": item["projection_metrics"]["matched_players"],
                "MAE": item["projection_metrics"]["mae"],
                "Bias": item["projection_metrics"]["bias"],
                "Correlation": item["projection_metrics"]["correlation"],
                "Coverage": item["projection_metrics"]["interval_coverage"],
                "Ownership MAE": item["projection_metrics"].get("ownership_mae"),
                "Best top %": item.get("best_top_percent"),
            }
            for item in records
        ])
        st.dataframe(
            history,
            column_config={
                "MAE": st.column_config.NumberColumn(format="%.2f"),
                "Bias": st.column_config.NumberColumn(format="%+.2f"),
                "Correlation": st.column_config.NumberColumn(format="%.2f"),
                "Coverage": st.column_config.NumberColumn(format="percent"),
                "Ownership MAE": st.column_config.NumberColumn(format="%.2f%%"),
                "Best top %": st.column_config.NumberColumn(format="%.2f%%"),
            },
            hide_index=True,
            width="stretch",
        )

if st.button("Back to results", icon=":material/arrow_back:", width="stretch"):
    st.switch_page("app_pages/results.py")
