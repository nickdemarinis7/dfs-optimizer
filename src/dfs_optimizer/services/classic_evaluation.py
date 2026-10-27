from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import mean, median


@dataclass(frozen=True, slots=True)
class ClassicScorecard:
    records: tuple[dict, ...]
    slates: int
    scored_portfolios: int
    submitted_entries: int
    weighted_projection_mae: float | None
    weighted_projection_bias: float | None
    weighted_ownership_mae: float | None
    weighted_ownership_bias: float | None
    best_top_percent_median: float | None
    average_top_percent: float | None
    top_ten_rate: float | None
    top_one_rate: float | None
    average_winner_gap: float | None
    lineup_zero_rate: float | None
    roi: float | None
    recurring_misses: tuple[dict, ...]
    prop_evaluation: dict
    data_gaps: tuple[str, ...]


def build_classic_scorecard(
    records: tuple[dict, ...], *, sport: str = "nfl"
) -> ClassicScorecard:
    """Aggregate verified Classic records without averaging slate averages.

    Only records whose submitted entries were matched back to the current app
    run contribute contest-finish metrics. Projection and ownership diagnostics
    can still use a record when the player results were parsed successfully.
    """
    filtered = _latest_by_run_id(tuple(
        item for item in records
        if item.get("contest_format") == "classic"
        and item.get("sport", "nfl") == sport
    ))
    scored = tuple(item for item in filtered if (item.get("submitted_entries") or 0) > 0)
    projection_samples = sum(
        item.get("projection_metrics", {}).get("matched_players", 0) or 0
        for item in filtered
    )
    ownership_samples = sum(
        item.get("projection_metrics", {}).get("ownership_samples", 0) or 0
        for item in filtered
    )
    lineup_slots = sum(item.get("lineup_roster_slots", 0) or 0 for item in filtered)
    zero_slots = sum(item.get("lineup_zero_slots", 0) or 0 for item in filtered)
    best_finishes = [item["best_top_percent"] for item in scored
                     if item.get("best_top_percent") is not None]
    average_finishes = [item["average_top_percent"] for item in scored
                        if item.get("average_top_percent") is not None]
    winner_gaps = [
        item["winning_score"] - item["best_score"] for item in scored
        if item.get("winning_score") is not None and item.get("best_score") is not None
    ]
    cost_records = [item for item in scored if item.get("entry_cost")]
    cost = sum(item["entry_cost"] for item in cost_records)
    winnings = sum(item.get("total_winnings") or 0 for item in cost_records)
    gaps = []
    if not filtered:
        gaps.append("No saved NFL Classic calibration records are available yet.")
    if len(filtered) < 3:
        gaps.append("At least three slates are needed before changing strategy defaults.")
    if len(scored) < len(filtered):
        gaps.append(
            f"{len(filtered) - len(scored)} slate(s) lack verified current-run entries; "
            "their contest finishes are excluded."
        )
    if ownership_samples == 0:
        gaps.append("No actual contest ownership is available for calibration.")

    return ClassicScorecard(
        records=filtered,
        slates=len(filtered),
        scored_portfolios=len(scored),
        submitted_entries=sum(item.get("submitted_entries", 0) or 0 for item in scored),
        weighted_projection_mae=_weighted_metric(
            filtered, "matched_players", "mae"
        ),
        weighted_projection_bias=_weighted_metric(
            filtered, "matched_players", "bias"
        ),
        weighted_ownership_mae=_weighted_metric(
            filtered, "ownership_samples", "ownership_mae"
        ),
        weighted_ownership_bias=_weighted_metric(
            filtered, "ownership_samples", "ownership_bias"
        ),
        best_top_percent_median=median(best_finishes) if best_finishes else None,
        average_top_percent=mean(average_finishes) if average_finishes else None,
        top_ten_rate=(
            sum(value <= 10 for value in best_finishes) / len(best_finishes)
            if best_finishes else None
        ),
        top_one_rate=(
            sum(value <= 1 for value in best_finishes) / len(best_finishes)
            if best_finishes else None
        ),
        average_winner_gap=mean(winner_gaps) if winner_gaps else None,
        lineup_zero_rate=zero_slots / lineup_slots if lineup_slots else None,
        roi=(winnings - cost) / cost if cost else None,
        recurring_misses=_recurring_player_misses(filtered),
        prop_evaluation=_evaluate_prop_adjustments(filtered),
        data_gaps=tuple(gaps),
    )


def scorecard_rows(scorecard: ClassicScorecard) -> tuple[dict, ...]:
    return tuple({
        "Run": item.get("run_id"),
        "Platform": item.get("platform", "").title(),
        "Players": item.get("projection_metrics", {}).get("matched_players"),
        "Projection MAE": item.get("projection_metrics", {}).get("mae"),
        "Ownership MAE": item.get("projection_metrics", {}).get("ownership_mae"),
        "Entries": item.get("submitted_entries", 0),
        "Best top %": item.get("best_top_percent"),
        "Average top %": item.get("average_top_percent"),
        "Winner gap": (
            item["winning_score"] - item["best_score"]
            if item.get("winning_score") is not None and item.get("best_score") is not None
            else None
        ),
        "Lineup zero rate": item.get("lineup_zero_rate"),
        "Strategy": item.get("strategy_version"),
    } for item in scorecard.records)


def _latest_by_run_id(records: tuple[dict, ...]) -> tuple[dict, ...]:
    output = {}
    for item in sorted(records, key=lambda row: row.get("recorded_at_utc", "")):
        output[item.get("run_id") or f"anonymous-{len(output)}"] = item
    return tuple(output.values())


def _weighted_metric(records, sample_key: str, metric_key: str) -> float | None:
    pairs = [
        (item.get("projection_metrics", {}).get(sample_key, 0) or 0,
         item.get("projection_metrics", {}).get(metric_key))
        for item in records
    ]
    total = sum(samples for samples, value in pairs if value is not None)
    return (
        sum(samples * value for samples, value in pairs if value is not None) / total
        if total else None
    )


def _recurring_player_misses(records: tuple[dict, ...]) -> tuple[dict, ...]:
    players = defaultdict(list)
    for record in records:
        for row in record.get("player_calibration", ()):
            if row.get("projected_points") is None or row.get("actual_points") is None:
                continue
            players[row.get("player", "Unknown")].append(
                row["projected_points"] - row["actual_points"]
            )
    return tuple(sorted(({
        "Player": player,
        "Slates": len(errors),
        "MAE": mean(abs(value) for value in errors),
        "Bias": mean(errors),
    } for player, errors in players.items() if len(errors) >= 2),
        key=lambda row: row["MAE"], reverse=True,
    )[:15])


def _evaluate_prop_adjustments(records: tuple[dict, ...]) -> dict:
    original_errors = []
    adjusted_errors = []
    for record in records:
        actuals = {
            row.get("player"): row.get("actual_points")
            for row in record.get("player_calibration", ())
        }
        for adjustment in record.get("nfl_prop_adjustments", ()):
            actual = actuals.get(adjustment.get("player"))
            if actual is None:
                continue
            original_errors.append(abs(adjustment["original_projection"] - actual))
            adjusted_errors.append(abs(adjustment["adjusted_projection"] - actual))
    return {
        "samples": len(original_errors),
        "original_mae": mean(original_errors) if original_errors else None,
        "adjusted_mae": mean(adjusted_errors) if adjusted_errors else None,
        "mae_change": (
            mean(adjusted_errors) - mean(original_errors) if original_errors else None
        ),
    }
