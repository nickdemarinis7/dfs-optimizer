from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from dfs_optimizer.app_ui import action_guide, apply_platform_theme, hero, page_kicker
from dfs_optimizer.backtesting import (
    evaluate_projection_rows,
    evaluate_projections,
    import_player_results_content,
)
from dfs_optimizer.services.results_review import (
    extract_submitted_entries,
    review_contest_results,
)
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
    "How did they finish?",
    "Drop in the contest standings after it ends. We’ll find your generated lineups and grade the run automatically.",
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
            st.subheader("Actual submitted entries")
            if submitted:
                st.dataframe(
                    pd.DataFrame([
                        {
                            "Rank": item.rank,
                            "Score": item.score,
                            "Top %": round(100 * item.rank / review.field_size, 2),
                            "Duplicates": item.duplication,
                            "Lineup": ", ".join(
                                f"{role} {name}".strip()
                                for role, name in item.lineup
                            ),
                        }
                        for item in submitted
                    ]),
                    hide_index=True,
                    width="stretch",
                )
                if len(submitted) != len(lineups) or len(review.lineups) != len(submitted):
                    st.info(
                        "Your final submitted entries differ from this saved run. "
                        "The table above is authoritative for post-contest review."
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
            result_hash = hashlib.sha256(results_file.getvalue()).hexdigest()
            run_id = st.session_state.get("current_run_id") or f"results-{result_hash[:12]}"
            record = calibration_record(
                run_id,
                slate,
                projection_metrics,
                evaluation_rows,
                review.field_size,
                review.winning_score,
                submitted,
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
                "Best top %": st.column_config.NumberColumn(format="%.2f%%"),
            },
            hide_index=True,
            width="stretch",
        )

if st.button("Back to results", icon=":material/arrow_back:", width="stretch"):
    st.switch_page("app_pages/results.py")
