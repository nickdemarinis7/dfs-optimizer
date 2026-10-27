from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import streamlit as st

from dfs_optimizer.app_state import restore_run_session
from dfs_optimizer.app_ui import action_guide, apply_platform_theme, hero, page_kicker
from dfs_optimizer.models import ContestFormat
from dfs_optimizer.backtesting import (
    evaluate_projection_rows,
    evaluate_projections,
    import_player_results_content,
)
from dfs_optimizer.services.results_review import (
    CapturedSubmission,
    SavedPortfolio,
    analyze_winner_strategies,
    classify_submitted_entry_provenance,
    extract_submitted_entries,
    review_contest_results,
)
from dfs_optimizer.services import scenarios as _scenarios

if "script_type" not in getattr(
    _scenarios.LineupScenarioAnalysis, "__dataclass_fields__", {}
):
    from importlib import reload

    _scenarios = reload(_scenarios)
simulate_lineups = _scenarios.simulate_lineups
validate_lineup_scripts = _scenarios.validate_lineup_scripts
from dfs_optimizer.services.run_history import (
    import_run_archive,
    list_run_records,
    restore_run,
    restore_shadow_run,
)
from dfs_optimizer.services.experiments import evaluate_weekly_context_experiment
from dfs_optimizer.services.submissions import load_submission_snapshot
from dfs_optimizer.services.calibration import (
    aggregate_calibration_segments,
    aggregate_weekly_adjustment_performance,
    aggregate_winner_strategy_bands,
    calibration_excluded_player_names,
    calibration_record,
    calibration_record_bytes,
    calibration_history_bytes,
    import_calibration_records,
    list_calibration_records,
    save_calibration_record,
)
from dfs_optimizer.services.classic_evaluation import (
    build_classic_scorecard,
    scorecard_rows,
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
    with st.container(border=True):
        st.subheader("Restore the run you want to grade")
        st.caption(
            "Upload the complete run-package ZIP you downloaded when the lineups "
            "were generated. Add the submission snapshot too if the entered "
            "rosters differed from the generated portfolio."
        )
        with st.form("backtest-run-import", border=False):
            run_upload = st.file_uploader(
                "Complete run package",
                type="zip",
                key="backtest-run-package",
                help="Upload the dfs-run ZIP—not the contest standings ZIP.",
            )
            submission_upload = st.file_uploader(
                "Final-submission snapshot (optional)",
                type="json",
                key="backtest-submission-snapshot",
            )
            restore_clicked = st.form_submit_button(
                "Restore run for grading",
                icon=":material/restore:",
                type="primary",
                width="stretch",
            )
        if restore_clicked:
            if run_upload is None:
                st.warning("Choose a complete run-package ZIP first.")
            else:
                try:
                    record = import_run_archive(
                        run_upload.getvalue(),
                        st.session_state.get("run_directory", "data/runs"),
                    )
                    submission_content = None
                    if submission_upload is not None:
                        submission_content = submission_upload.getvalue()
                        snapshot = load_submission_snapshot(submission_content)
                        if snapshot.run_id != record.run_id:
                            raise ValueError(
                                "the submission snapshot belongs to a different run"
                            )
                        if (
                            snapshot.platform != record.platform
                            or snapshot.contest_format != record.contest_format
                        ):
                            raise ValueError(
                                "the submission snapshot does not match this slate"
                            )
                    restore_run_session(st.session_state, record)
                    if submission_content is not None:
                        st.session_state["submission_snapshot"] = submission_content
                    st.session_state["backtest-restore-message"] = (
                        f"Restored {record.label}. Upload the final standings below."
                    )
                except (KeyError, OSError, ValueError) as exc:
                    st.error(f"Could not restore this run: {exc}")
                else:
                    st.rerun()
    if st.button("Back to lineup builder", icon=":material/arrow_back:", width="stretch"):
        st.switch_page("app_pages/build.py")
    st.stop()

if message := st.session_state.pop("backtest-restore-message", None):
    st.success(message, icon=":material/verified:")

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
with st.expander("Contest cost and return (optional)"):
    entry_fee = float(st.number_input(
        "Entry fee per submitted lineup", min_value=0.0, value=0.0, step=1.0,
        help="Used with the verified current-run entries to calculate total cost and ROI.",
    ))
    total_winnings = float(st.number_input(
        "Total winnings", min_value=0.0, value=0.0, step=1.0,
        help="Enter zero when the submitted entries did not cash.",
    ))

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

        strategy_report = analyze_winner_strategies(
            results_file.getvalue(), results_file.name, slate
        )
        st.subheader("What worked at the top")
        st.caption(
            "Exact copies are collapsed so heavily duplicated rosters do not count "
            "as separate strategies. Use repeated patterns across slates as evidence; "
            "do not treat one winner as a new hard rule."
        )
        strategy_rows = []
        for band in strategy_report.bands:
            row = {
                    "Finish band": band.label,
                    "Unique lineups": band.unique_lineups,
                    "Average score": band.average_score,
                    "Average duplicates": band.average_duplication,
                    "Average salary left": band.average_salary_left,
                    "Average player ownership": band.average_ownership,
                    "Average sub-5% plays": band.average_low_owned_players,
            }
            if slate.contest_format == ContestFormat.SINGLE_GAME:
                row.update({
                    "Average QBs": band.average_quarterbacks,
                    "Average K/DST": band.average_kickers_and_defenses,
                    "Average max team players": band.average_max_team_players,
                    "Receiver multiplier + QB rate": (
                        band.receiver_multiplier_qb_pair_rate
                    ),
                })
            else:
                row.update({
                    "QB stack rate": band.qb_stack_rate,
                    "Bring-back rate": band.bring_back_rate,
                    "Double-TE rate": band.double_te_rate,
                })
            strategy_rows.append(row)
        st.dataframe(
            pd.DataFrame(strategy_rows),
            column_config={
                "Average score": st.column_config.NumberColumn(format="%.2f"),
                "Average duplicates": st.column_config.NumberColumn(format="%.1f"),
                "Average salary left": st.column_config.NumberColumn(format="$%.0f"),
                "Average player ownership": st.column_config.NumberColumn(format="%.1f%%"),
                "Average sub-5% plays": st.column_config.NumberColumn(format="%.1f"),
                "QB stack rate": st.column_config.NumberColumn(format="percent"),
                "Bring-back rate": st.column_config.NumberColumn(format="percent"),
                "Double-TE rate": st.column_config.NumberColumn(format="percent"),
                "Average QBs": st.column_config.NumberColumn(format="%.2f"),
                "Average K/DST": st.column_config.NumberColumn(format="%.2f"),
                "Average max team players": st.column_config.NumberColumn(format="%.2f"),
                "Receiver multiplier + QB rate": st.column_config.NumberColumn(
                    format="percent"
                ),
            },
            hide_index=True,
            width="stretch",
        )
        for winner_number, winner in enumerate(strategy_report.winner_lineups, 1):
            with st.container(border=True):
                st.markdown(f"**Winning construction {winner_number}**")
                st.caption(
                    f"{winner.score:.2f} points · {winner.duplication:,} exact "
                    f"cop{'y' if winner.duplication == 1 else 'ies'}"
                )
                st.markdown(" · ".join(
                    f"**{role}** {name}" if role else name
                    for role, name in winner.lineup
                ))

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
            saved_runs = list_run_records(
                st.session_state.get("run_directory", "data/runs")
            )
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
            snapshot_content = st.session_state.get("submission_snapshot")
            snapshot_path_value = st.session_state.get("saved_submission_path")
            snapshot_path = (
                Path(snapshot_path_value)
                if snapshot_path_value
                else Path("data/submissions") / f"{current_run_id}.json"
                if current_run_id else None
            )
            if snapshot_content or (
                snapshot_path is not None and snapshot_path.is_file()
            ):
                try:
                    snapshot = load_submission_snapshot(
                        snapshot_content or snapshot_path
                    )
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
                            "Zero-point players": (
                                ", ".join(item.zero_point_players) or "—"
                            ),
                            "Entry": item.entry_name,
                    }
                    for item in review.lineups
                ]),
                hide_index=True,
                width="stretch",
            )
            lineup_zero_players = sorted({
                name
                for item in review.lineups
                for name in item.zero_point_players
            })
            lineup_slots = sum(item.roster_slots for item in review.lineups)
            lineup_zero_slots = sum(
                len(item.zero_point_players) for item in review.lineups
            )
            if lineup_zero_slots:
                st.error(
                    f"{lineup_zero_slots} of {lineup_slots} selected roster slots "
                    f"scored zero: {', '.join(lineup_zero_players)}. Review each "
                    "player for inactive/DNP, backup role, injury, or healthy zero usage.",
                    icon=":material/person_alert:",
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
            projected_names = {
                item.name.casefold(): item.name for item in projections
            }
            injury_options = tuple(sorted(
                projected_names[item.name.casefold()]
                for item in actuals
                if item.name.casefold() in projected_names
            ))
            injury_censored_players = tuple(st.multiselect(
                "Players who exited early with an in-game injury",
                injury_options,
                key=f"injury-censored-{hashlib.sha256(results_file.getvalue()).hexdigest()[:12]}",
                help=(
                    "Their actual points still grade every lineup, but they are "
                    "excluded from projection-error calibration so an unforeseeable "
                    "early exit does not teach the model that the pregame role was wrong."
                ),
                placeholder="Select only confirmed early exits",
            ))
            if injury_censored_players:
                st.info(
                    "Lineup standings are unchanged. Calibration excludes: "
                    + ", ".join(injury_censored_players),
                    icon=":material/healing:",
                )
            run_settings = st.session_state.get("lineup_settings", {})
            automatically_screened_names = tuple(
                run_settings.get("automatic_exclusion_suggestions") or ()
            )
            excluded_actual_names = calibration_excluded_player_names(
                run_settings, injury_censored_players
            )
            projection_metrics = evaluate_projections(
                tuple(projections), actuals,
                excluded_player_names=excluded_actual_names,
            )
            evaluation_rows = evaluate_projection_rows(
                tuple(projections), actuals,
                excluded_player_names=excluded_actual_names,
            )
            screened_keys = {name.casefold() for name in automatically_screened_names}
            screening_rows = evaluate_projection_rows(
                tuple(
                    item for item in projections
                    if item.name.casefold() in screened_keys
                ),
                actuals,
            )
            ab_evaluation = None
            current_run_id = st.session_state.get("current_run_id")
            current_record = next(
                (
                    item for item in list_run_records(
                        st.session_state.get("run_directory", "data/runs")
                    )
                    if item.run_id == current_run_id
                ),
                None,
            )
            if current_record is not None:
                control_projections, control_lineups = restore_shadow_run(current_record)
                if control_projections and control_lineups:
                    ab_evaluation = evaluate_weekly_context_experiment(
                        tuple(projections), tuple(lineups),
                        control_projections, control_lineups, actuals,
                        excluded_player_names=excluded_actual_names,
                    )
        except ValueError as exc:
            st.info(f"Player-level evaluation is unavailable: {exc}")
        else:
            if ab_evaluation is not None:
                st.subheader("Weekly-context A/B result")
                st.caption(
                    "The entered treatment used injury, practice, weather, rest, "
                    "and role context. The hidden control used the same slate and "
                    "optimizer settings without those weekly projection adjustments."
                )
                ab_columns = st.columns(3)
                ab_columns[0].metric(
                    "Projection MAE change",
                    f"{ab_evaluation.mae_change:+.2f}",
                    help="Negative is better: the weekly-context treatment had less projection error.",
                )
                ab_columns[1].metric(
                    "Average lineup change",
                    f"{ab_evaluation.average_lineup_score_change:+.2f} pts",
                )
                ab_columns[2].metric(
                    "Best lineup change",
                    f"{ab_evaluation.best_lineup_score_change:+.2f} pts",
                )
                st.dataframe(
                    pd.DataFrame([
                        {
                            "Variant": "Weekly context (treatment)",
                            "Projection MAE": ab_evaluation.treatment_metrics.mean_absolute_error,
                            "Average lineup": sum(ab_evaluation.treatment_lineup_scores) / len(ab_evaluation.treatment_lineup_scores),
                            "Best lineup": max(ab_evaluation.treatment_lineup_scores),
                        },
                        {
                            "Variant": "No weekly context (control)",
                            "Projection MAE": ab_evaluation.control_metrics.mean_absolute_error,
                            "Average lineup": sum(ab_evaluation.control_lineup_scores) / len(ab_evaluation.control_lineup_scores),
                            "Best lineup": max(ab_evaluation.control_lineup_scores),
                        },
                    ]),
                    column_config={
                        column: st.column_config.NumberColumn(format="%.2f")
                        for column in ("Projection MAE", "Average lineup", "Best lineup")
                    },
                    hide_index=True,
                    width="stretch",
                )
            if screening_rows:
                with st.container(border=True):
                    st.markdown("**Pre-lock screening audit**")
                    st.caption(
                        "These players were automatically removed before optimization. "
                        "Their outcomes grade the player-pool decision but are excluded "
                        "from projection-error calibration."
                    )
                    st.dataframe(
                        pd.DataFrame([{
                            "Player": row.name,
                            "Projected": row.projected,
                            "Actual": row.actual,
                            "Would have exceeded projection": row.actual > row.projected,
                        } for row in screening_rows]),
                        column_config={
                            "Projected": st.column_config.NumberColumn(format="%.2f"),
                            "Actual": st.column_config.NumberColumn(format="%.2f"),
                        },
                        hide_index=True,
                        width="stretch",
                    )
            if slate.contest_format == ContestFormat.SINGLE_GAME:
                scenario_analysis = st.session_state.get("scenario_analysis", ())
                if len(scenario_analysis) != len(lineups):
                    scenario_analysis = simulate_lineups(lineups)
                teams = tuple(sorted(slate.teams))
                team_scores = None
                with st.container(border=True):
                    st.markdown("**Did the predicted game scripts happen?**")
                    add_final_score = st.toggle(
                        "Add the final game score",
                        help="This is required to validate a low-scoring special-teams script without guessing from fantasy points.",
                    )
                    if add_final_score and len(teams) == 2:
                        score_columns = st.columns(2)
                        team_scores = {
                            team: int(score_columns[index].number_input(
                                f"{team} final points", min_value=0, max_value=100,
                                value=0, step=1,
                            ))
                            for index, team in enumerate(teams)
                        }
                    script_validation = validate_lineup_scripts(
                        lineups, tuple(scenario_analysis), actuals, team_scores
                    )
                    st.dataframe(
                        pd.DataFrame([{
                            "Lineup": item.lineup_number,
                            "Predicted script": item.predicted_script,
                            "Verdict": item.verdict,
                            "Evidence": item.evidence,
                        } for item in script_validation]),
                        hide_index=True,
                        width="stretch",
                    )
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
            zero_columns = st.columns(2)
            zero_columns[0].metric(
                "Zero-point players", projection_metrics.zero_point_players
            )
            zero_columns[1].metric(
                "Zero-point rate", f"{projection_metrics.zero_point_rate:.1%}"
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
            player_by_name = {
                "".join(character for character in player.name.casefold() if character.isalnum()): player
                for player in slate.players
            }
            evaluation_frame["Salary"] = [
                player_by_name.get(
                    "".join(character for character in row.name.casefold() if character.isalnum())
                ).salary
                if player_by_name.get(
                    "".join(character for character in row.name.casefold() if character.isalnum())
                ) else None
                for row in evaluation_rows
            ]
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
                review.lineups,
                entry_fee=entry_fee if entry_fee > 0 else None,
                total_winnings=total_winnings if entry_fee > 0 else None,
                winner_strategy_report=strategy_report,
                injury_censored_players=injury_censored_players,
            )
            record["strategy_version"] = run_settings.get("strategy_version")
            record["nfl_prop_adjustments"] = list(
                run_settings.get("nfl_prop_adjustments") or ()
            )
            record["classic_candidate_diagnostics"] = (
                run_settings.get("classic_candidate_diagnostics")
            )
            record["weekly_projection_adjustments"] = list(
                run_settings.get("weekly_projection_adjustments") or ()
            )
            if ab_evaluation is not None:
                record["weekly_context_experiment"] = {
                    "name": "weekly-context-ab-v1",
                    "treatment_projection_mae": ab_evaluation.treatment_metrics.mean_absolute_error,
                    "control_projection_mae": ab_evaluation.control_metrics.mean_absolute_error,
                    "mae_change": ab_evaluation.mae_change,
                    "treatment_lineup_scores": list(ab_evaluation.treatment_lineup_scores),
                    "control_lineup_scores": list(ab_evaluation.control_lineup_scores),
                    "average_lineup_score_change": ab_evaluation.average_lineup_score_change,
                    "best_lineup_score_change": ab_evaluation.best_lineup_score_change,
                }
            record["prelock_screening"] = [{
                "player": row.name,
                "projected_points": row.projected,
                "actual_points": row.actual,
                "exceeded_projection": row.actual > row.projected,
            } for row in screening_rows]
            if slate.contest_format == ContestFormat.SINGLE_GAME:
                record["script_validation"] = [
                    {
                        "lineup_number": item.lineup_number,
                        "predicted_script": item.predicted_script,
                        "verdict": item.verdict,
                        "evidence": item.evidence,
                    }
                    for item in script_validation
                ]
                record["final_team_scores"] = team_scores
            if record.get("roi") is not None:
                return_columns = st.columns(3)
                return_columns[0].metric("Entry cost", f"${record['entry_cost']:.2f}")
                return_columns[1].metric("Winnings", f"${record['total_winnings']:.2f}")
                return_columns[2].metric("ROI", f"{record['roi']:+.1%}")
            segment_columns = st.columns(2)
            for column, title, key in (
                (segment_columns[0], "Error by salary tier", "salary_metrics"),
                (segment_columns[1], "Error by confidence tier", "confidence_metrics"),
            ):
                with column:
                    st.caption(title)
                    st.dataframe(
                        pd.DataFrame([
                            {
                                "Tier": name,
                                "Players": values["players"],
                                "MAE": values["mae"],
                                "Bias": values["bias"],
                                "Zero rate": values["zero_rate"],
                                "Ownership MAE": values["ownership_mae"],
                            }
                            for name, values in record[key].items()
                        ]),
                        column_config={
                            "MAE": st.column_config.NumberColumn(format="%.2f"),
                            "Bias": st.column_config.NumberColumn(format="%+.2f"),
                            "Zero rate": st.column_config.NumberColumn(format="percent"),
                            "Ownership MAE": st.column_config.NumberColumn(format="%.2f%%"),
                        },
                        hide_index=True,
                        width="stretch",
                    )
            record_key = (
                run_id, result_hash, entry_filter.strip().casefold(),
                entry_fee, total_winnings, injury_censored_players,
                automatically_screened_names,
            )
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

saved_records = list_calibration_records()
history_files = st.file_uploader(
    "Previous calibration records (optional)",
    type="json",
    accept_multiple_files=True,
    help=(
        "Upload records downloaded after earlier slates. This keeps the multi-slate "
        "scorecard portable when Streamlit Cloud restarts."
    ),
)
uploaded_records = []
for history_file in history_files or ():
    try:
        uploaded_records.extend(import_calibration_records(history_file.getvalue()))
    except ValueError as exc:
        st.error(f"{history_file.name}: {exc}", icon=":material/error:")
records = tuple(saved_records) + tuple(uploaded_records)
if records:
    classic_scorecard = build_classic_scorecard(records)
    with st.container(border=True):
        st.subheader("NFL Classic scorecard")
        st.caption(
            "Only entries verified against the matching app run affect finish-rate "
            "metrics. Player projections can still be calibrated when no entry was submitted."
        )
        scorecard_metrics = st.columns(3)
        scorecard_metrics[0].metric("Slates", classic_scorecard.slates)
        scorecard_metrics[1].metric(
            "Median best finish",
            f"Top {classic_scorecard.best_top_percent_median:.2f}%"
            if classic_scorecard.best_top_percent_median is not None else "—",
        )
        scorecard_metrics[2].metric(
            "Projection MAE",
            f"{classic_scorecard.weighted_projection_mae:.2f}"
            if classic_scorecard.weighted_projection_mae is not None else "—",
        )
        finish_metrics = st.columns(3)
        finish_metrics[0].metric(
            "Top-10% slate rate",
            f"{classic_scorecard.top_ten_rate:.0%}"
            if classic_scorecard.top_ten_rate is not None else "—",
        )
        finish_metrics[1].metric(
            "Average winner gap",
            f"{classic_scorecard.average_winner_gap:.2f} pts"
            if classic_scorecard.average_winner_gap is not None else "—",
        )
        finish_metrics[2].metric(
            "Ownership MAE",
            f"{classic_scorecard.weighted_ownership_mae:.2f}%"
            if classic_scorecard.weighted_ownership_mae is not None else "—",
        )
        if classic_scorecard.data_gaps:
            for gap in classic_scorecard.data_gaps:
                st.info(gap, icon=":material/info:")
        if classic_scorecard.records:
            st.dataframe(
                pd.DataFrame(scorecard_rows(classic_scorecard)),
                column_config={
                    "Projection MAE": st.column_config.NumberColumn(format="%.2f"),
                    "Ownership MAE": st.column_config.NumberColumn(format="%.2f%%"),
                    "Best top %": st.column_config.NumberColumn(format="%.2f%%"),
                    "Average top %": st.column_config.NumberColumn(format="%.2f%%"),
                    "Winner gap": st.column_config.NumberColumn(format="%.2f"),
                    "Lineup zero rate": st.column_config.NumberColumn(format="percent"),
                },
                hide_index=True,
                width="stretch",
            )
            st.download_button(
                "Download combined Classic history",
                calibration_history_bytes(classic_scorecard.records),
                "nfl-classic-calibration-history.json",
                "application/json",
                icon=":material/download:",
                width="stretch",
            )
        if classic_scorecard.recurring_misses:
            st.caption("Recurring player-level misses")
            st.dataframe(
                pd.DataFrame(classic_scorecard.recurring_misses),
                column_config={
                    "MAE": st.column_config.NumberColumn(format="%.2f"),
                    "Bias": st.column_config.NumberColumn(format="%+.2f"),
                },
                hide_index=True,
                width="stretch",
            )
        prop_evaluation = classic_scorecard.prop_evaluation
        if prop_evaluation["samples"]:
            direction = "improved" if prop_evaluation["mae_change"] < 0 else "worsened"
            st.caption(
                f"Prop adjustments: {prop_evaluation['samples']} graded players · "
                f"MAE {direction} by {abs(prop_evaluation['mae_change']):.2f} points."
            )

    with st.expander("Calibration history", icon=":material/monitoring:"):
        history = pd.DataFrame([
            {
                "Run": item["run_id"],
                "Platform": item["platform"],
                "Sport": item.get("sport", "unknown").upper(),
                "Format": item["contest_format"].replace("_", " ").title(),
                "Players": item["projection_metrics"]["matched_players"],
                "MAE": item["projection_metrics"]["mae"],
                "Bias": item["projection_metrics"]["bias"],
                "Correlation": item["projection_metrics"]["correlation"],
                "Coverage": item["projection_metrics"]["interval_coverage"],
                "Ownership MAE": item["projection_metrics"].get("ownership_mae"),
                "Zero rate": item["projection_metrics"].get("zero_point_rate"),
                "Lineup zero rate": item.get("lineup_zero_rate"),
                "Best top %": item.get("best_top_percent"),
                "Average top %": item.get("average_top_percent"),
                "ROI": item.get("roi"),
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
                "Zero rate": st.column_config.NumberColumn(format="percent"),
                "Lineup zero rate": st.column_config.NumberColumn(format="percent"),
                "Best top %": st.column_config.NumberColumn(format="%.2f%%"),
                "Average top %": st.column_config.NumberColumn(format="%.2f%%"),
                "ROI": st.column_config.NumberColumn(format="percent"),
            },
            hide_index=True,
            width="stretch",
        )
        dashboard_platform = st.selectbox(
            "Calibration dashboard platform",
            ("All", *sorted({item["platform"] for item in records})),
        )
        available_sports = sorted({item.get("sport", "unknown") for item in records})
        dashboard_sport = st.selectbox(
            "Calibration dashboard sport",
            ("All", *available_sports),
        )
        available_formats = sorted({item["contest_format"] for item in records})
        dashboard_format = st.selectbox(
            "Calibration dashboard format",
            ("All", *available_formats),
            format_func=lambda value: value.replace("_", " ").title(),
        )
        dashboard_records = tuple(
            item for item in records
            if dashboard_platform == "All" or item["platform"] == dashboard_platform
            if dashboard_sport == "All" or item.get("sport", "unknown") == dashboard_sport
            if dashboard_format == "All" or item["contest_format"] == dashboard_format
        )
        total_players = sum(
            item["projection_metrics"]["matched_players"]
            for item in dashboard_records
        )
        if total_players:
            dashboard_metrics = st.columns(4)
            dashboard_metrics[0].metric("Slates", len(dashboard_records))
            dashboard_metrics[1].metric("Players", total_players)
            dashboard_metrics[2].metric(
                "Weighted MAE",
                f"{sum(item['projection_metrics']['mae'] * item['projection_metrics']['matched_players'] for item in dashboard_records) / total_players:.2f}",
            )
            roi_records = [item for item in dashboard_records if item.get("entry_cost")]
            aggregate_cost = sum(item["entry_cost"] for item in roi_records)
            aggregate_winnings = sum(item.get("total_winnings") or 0 for item in roi_records)
            dashboard_metrics[3].metric(
                "Portfolio ROI",
                f"{(aggregate_winnings - aggregate_cost) / aggregate_cost:+.1%}"
                if aggregate_cost else "—",
            )
        for title, key in (
            ("By position", "position_metrics"),
            ("By salary tier", "salary_metrics"),
            ("By confidence tier", "confidence_metrics"),
        ):
            segments = aggregate_calibration_segments(dashboard_records, key)
            if not segments:
                continue
            st.caption(title)
            st.dataframe(
                pd.DataFrame([
                    {
                        "Segment": name,
                        "Players": values["players"],
                        "MAE": values["mae"],
                        "Bias": values["bias"],
                        "Zero rate": values["zero_rate"],
                        "Ownership MAE": values["ownership_mae"],
                        "Ownership bias": values["ownership_bias"],
                    }
                    for name, values in segments.items()
                ]),
                column_config={
                    "MAE": st.column_config.NumberColumn(format="%.2f"),
                    "Bias": st.column_config.NumberColumn(format="%+.2f"),
                    "Zero rate": st.column_config.NumberColumn(format="percent"),
                    "Ownership MAE": st.column_config.NumberColumn(format="%.2f%%"),
                    "Ownership bias": st.column_config.NumberColumn(format="%+.2f%%"),
                },
                hide_index=True,
                width="stretch",
            )
        winner_bands = aggregate_winner_strategy_bands(dashboard_records)
        if winner_bands:
            st.caption("Winning construction patterns")
            st.dataframe(
                pd.DataFrame([
                    {
                        "Finish band": label,
                        "Slates": values["slates"],
                        "Unique lineups": values["unique_lineups"],
                        "Average score": values["average_score"],
                        "Average duplicates": values["average_duplication"],
                        "Average salary left": values["average_salary_left"],
                        "Average player ownership": values["average_ownership"],
                        "Average sub-5% plays": values["average_low_owned_players"],
                        "QB stack rate": values["qb_stack_rate"],
                        "Bring-back rate": values["bring_back_rate"],
                        "Double-TE rate": values["double_te_rate"],
                    }
                    for label, values in winner_bands.items()
                ]),
                column_config={
                    "Average score": st.column_config.NumberColumn(format="%.2f"),
                    "Average duplicates": st.column_config.NumberColumn(format="%.1f"),
                    "Average salary left": st.column_config.NumberColumn(format="$%.0f"),
                    "Average player ownership": st.column_config.NumberColumn(format="%.1f%%"),
                    "Average sub-5% plays": st.column_config.NumberColumn(format="%.1f"),
                    "QB stack rate": st.column_config.NumberColumn(format="percent"),
                    "Bring-back rate": st.column_config.NumberColumn(format="percent"),
                    "Double-TE rate": st.column_config.NumberColumn(format="percent"),
                },
                hide_index=True,
                width="stretch",
            )
        weekly_performance = aggregate_weekly_adjustment_performance(
            dashboard_records
        )
        if weekly_performance:
            st.caption("Weekly-context adjustment validation")
            st.dataframe(
                pd.DataFrame([{
                    "Signal": reason,
                    "Players": values["samples"],
                    "MAE before": values["before_mae"],
                    "MAE after": values["after_mae"],
                    "Average improvement": values["average_error_improvement"],
                    "Helpful rate": values["helpful_rate"],
                } for reason, values in weekly_performance.items()]),
                column_config={
                    "MAE before": st.column_config.NumberColumn(format="%.2f"),
                    "MAE after": st.column_config.NumberColumn(format="%.2f"),
                    "Average improvement": st.column_config.NumberColumn(format="%+.2f"),
                    "Helpful rate": st.column_config.NumberColumn(format="percent"),
                },
                hide_index=True,
                width="stretch",
            )

if st.button("Back to results", icon=":material/arrow_back:", width="stretch"):
    st.switch_page("app_pages/results.py")
