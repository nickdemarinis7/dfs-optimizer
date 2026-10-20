from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def projection_confidence_tier(row) -> str:
    """Classify the forecast using only signals preserved in an archived run."""
    if row.confidence_tier:
        return row.confidence_tier
    if row.floor is None or row.ceiling is None:
        return "Unrated"
    relative_range = (row.ceiling - row.floor) / max(1.0, row.projected)
    bust = row.bust_probability
    if relative_range <= 1 and (bust is None or bust <= .25):
        return "High"
    if relative_range <= 1.75 and (bust is None or bust <= .50):
        return "Medium"
    return "Low"


def _segment_metrics(rows) -> dict:
    rows = tuple(rows)
    ownership_rows = tuple(
        row for row in rows
        if row.projected_ownership is not None and row.actual_ownership is not None
    )
    ownership_errors = tuple(
        row.projected_ownership - row.actual_ownership for row in ownership_rows
    )
    return {
        "players": len(rows),
        "mae": sum(row.absolute_error for row in rows) / len(rows),
        "bias": sum(row.error for row in rows) / len(rows),
        "zero_rate": sum(row.actual == 0 for row in rows) / len(rows),
        "absolute_error_total": sum(row.absolute_error for row in rows),
        "error_total": sum(row.error for row in rows),
        "zero_players": sum(row.actual == 0 for row in rows),
        "ownership_samples": len(ownership_rows),
        "ownership_mae": (
            sum(abs(error) for error in ownership_errors) / len(ownership_errors)
            if ownership_errors else None
        ),
        "ownership_bias": (
            sum(ownership_errors) / len(ownership_errors)
            if ownership_errors else None
        ),
        "ownership_absolute_error_total": sum(
            abs(error) for error in ownership_errors
        ),
        "ownership_error_total": sum(ownership_errors),
    }


def _group_metrics(rows, classifier) -> dict:
    groups = {}
    for row in rows:
        groups.setdefault(classifier(row), []).append(row)
    return {name: _segment_metrics(values) for name, values in groups.items()}


def aggregate_calibration_segments(records: tuple[dict, ...], key: str) -> dict:
    """Combine saved segment totals without averaging slate-level averages."""
    totals: dict[str, dict] = {}
    for record in records:
        for name, metrics in record.get(key, {}).items():
            target = totals.setdefault(name, {
                "players": 0, "absolute_error_total": 0.0,
                "error_total": 0.0, "zero_players": 0,
                "ownership_samples": 0,
                "ownership_absolute_error_total": 0.0,
                "ownership_error_total": 0.0,
            })
            players = metrics.get("players", 0) or 0
            ownership_samples = metrics.get("ownership_samples", 0) or 0
            fallbacks = {
                "players": players,
                "absolute_error_total": (metrics.get("mae") or 0) * players,
                "error_total": (metrics.get("bias") or 0) * players,
                "zero_players": (metrics.get("zero_rate") or 0) * players,
                "ownership_samples": ownership_samples,
                "ownership_absolute_error_total": (
                    (metrics.get("ownership_mae") or 0) * ownership_samples
                ),
                "ownership_error_total": (
                    (metrics.get("ownership_bias") or 0) * ownership_samples
                ),
            }
            for field in target:
                target[field] += metrics.get(field, fallbacks[field]) or 0
    output = {}
    for name, values in totals.items():
        players = values["players"]
        ownership_samples = values["ownership_samples"]
        output[name] = {
            "players": players,
            "mae": values["absolute_error_total"] / players if players else None,
            "bias": values["error_total"] / players if players else None,
            "zero_rate": values["zero_players"] / players if players else None,
            "ownership_samples": ownership_samples,
            "ownership_mae": (
                values["ownership_absolute_error_total"] / ownership_samples
                if ownership_samples else None
            ),
            "ownership_bias": (
                values["ownership_error_total"] / ownership_samples
                if ownership_samples else None
            ),
        }
    return output


def aggregate_winner_strategy_bands(records: tuple[dict, ...]) -> dict:
    """Combine saved winner-band summaries, weighted by unique constructions."""
    metrics = (
        "average_score", "average_duplication", "average_salary_left",
        "average_ownership", "average_low_owned_players", "qb_stack_rate",
        "bring_back_rate", "double_te_rate",
    )
    totals: dict[str, dict] = {}
    for record in records:
        for label, values in record.get("winner_strategy_bands", {}).items():
            count = values.get("unique_lineups", 0) or 0
            target = totals.setdefault(label, {
                "slates": 0, "unique_lineups": 0,
                **{f"{metric}_total": 0.0 for metric in metrics},
                **{f"{metric}_samples": 0 for metric in metrics},
            })
            target["slates"] += 1
            target["unique_lineups"] += count
            for metric in metrics:
                value = values.get(metric)
                if value is None:
                    continue
                target[f"{metric}_total"] += value * count
                target[f"{metric}_samples"] += count
    return {
        label: {
            "slates": values["slates"],
            "unique_lineups": values["unique_lineups"],
            **{
                metric: (
                    values[f"{metric}_total"] / values[f"{metric}_samples"]
                    if values[f"{metric}_samples"] else None
                )
                for metric in metrics
            },
        }
        for label, values in totals.items()
    }


def calibration_record(
    run_id: str,
    slate,
    metrics,
    evaluation_rows,
    field_size: int,
    winning_score: float,
    submitted_entries=(),
    reviewed_lineups=(),
    entry_fee: float | None = None,
    total_winnings: float | None = None,
    winner_strategy_report=None,
    injury_censored_players: tuple[str, ...] = (),
) -> dict:
    evaluation_rows = tuple(evaluation_rows)
    position_metrics = _group_metrics(evaluation_rows, lambda row: row.position or "Unknown")
    players_by_name = {
        "".join(character for character in player.name.casefold() if character.isalnum()): player
        for player in slate.players
    }
    matched_salaries = sorted(
        player.salary for player in players_by_name.values()
        if any(
            "".join(character for character in row.name.casefold() if character.isalnum())
            == "".join(character for character in player.name.casefold() if character.isalnum())
            for row in evaluation_rows
        )
    )
    lower_salary = matched_salaries[len(matched_salaries) // 3] if matched_salaries else 0
    upper_salary = matched_salaries[(2 * len(matched_salaries)) // 3] if matched_salaries else 0

    def salary_tier(row) -> str:
        player = players_by_name.get(
            "".join(character for character in row.name.casefold() if character.isalnum())
        )
        if player is None:
            return "Unknown"
        if player.salary < lower_salary:
            return "Value"
        if player.salary < upper_salary:
            return "Mid-range"
        return "Premium"

    salary_metrics = _group_metrics(evaluation_rows, salary_tier)
    confidence_metrics = _group_metrics(evaluation_rows, projection_confidence_tier)
    best = min(submitted_entries, key=lambda item: item.rank) if submitted_entries else None
    lineup_roster_slots = sum(item.roster_slots for item in reviewed_lineups)
    lineup_zero_slots = sum(
        len(item.zero_point_players) for item in reviewed_lineups
    )
    average_top_percent = (
        sum(item.top_percent for item in reviewed_lineups) / len(reviewed_lineups)
        if reviewed_lineups else None
    )
    entry_cost = (
        entry_fee * len(submitted_entries)
        if entry_fee is not None and submitted_entries else None
    )
    roi = (
        (total_winnings - entry_cost) / entry_cost
        if total_winnings is not None and entry_cost else None
    )
    return {
        "run_id": run_id,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform": slate.platform.value,
        "sport": slate.sport.value,
        "contest_format": slate.contest_format.value,
        "salary_source": slate.source_name,
        "field_size": field_size,
        "winning_score": winning_score,
        "injury_censored_players": list(injury_censored_players),
        "submitted_entries": len(submitted_entries),
        "best_rank": best.rank if best else None,
        "best_top_percent": 100 * best.rank / field_size if best else None,
        "best_score": best.score if best else None,
        "average_top_percent": average_top_percent,
        "entry_fee": entry_fee,
        "entry_cost": entry_cost,
        "total_winnings": total_winnings,
        "roi": roi,
        "lineup_roster_slots": lineup_roster_slots,
        "lineup_zero_slots": lineup_zero_slots,
        "lineup_zero_rate": (
            lineup_zero_slots / lineup_roster_slots if lineup_roster_slots else None
        ),
        "projection_metrics": {
            "matched_players": metrics.matched_players,
            "mae": metrics.mean_absolute_error,
            "rmse": metrics.root_mean_squared_error,
            "bias": metrics.mean_error,
            "correlation": metrics.correlation,
            "range_samples": metrics.range_samples,
            "interval_coverage": metrics.interval_coverage,
            "ceiling_exceed_rate": metrics.ceiling_exceed_rate,
            "ownership_samples": metrics.ownership_samples,
            "ownership_mae": metrics.ownership_mean_absolute_error,
            "ownership_bias": metrics.ownership_mean_error,
            "ownership_correlation": metrics.ownership_correlation,
            "zero_point_players": metrics.zero_point_players,
            "zero_point_rate": metrics.zero_point_rate,
        },
        "position_metrics": position_metrics,
        "salary_metrics": salary_metrics,
        "confidence_metrics": confidence_metrics,
        "winner_strategy_bands": {
            band.label: {
                "unique_lineups": band.unique_lineups,
                "average_score": band.average_score,
                "average_duplication": band.average_duplication,
                "average_salary_left": band.average_salary_left,
                "average_ownership": band.average_ownership,
                "average_low_owned_players": band.average_low_owned_players,
                "qb_stack_rate": band.qb_stack_rate,
                "bring_back_rate": band.bring_back_rate,
                "double_te_rate": band.double_te_rate,
            }
            for band in winner_strategy_report.bands
        } if winner_strategy_report is not None else {},
    }


def calibration_record_bytes(record: dict) -> bytes:
    return (json.dumps(record, indent=2) + "\n").encode()


def save_calibration_record(
    record: dict, directory: str | Path = "data/calibration"
) -> Path:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f"{record['run_id']}.json"
    temporary = root / f"{record['run_id']}.json.tmp"
    temporary.write_bytes(calibration_record_bytes(record))
    temporary.replace(destination)
    return destination


def list_calibration_records(
    directory: str | Path = "data/calibration",
) -> tuple[dict, ...]:
    root = Path(directory)
    records = []
    for path in root.glob("*.json") if root.is_dir() else ():
        try:
            records.append(json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError, KeyError):
            continue
    return tuple(sorted(
        records, key=lambda item: item.get("recorded_at_utc", ""), reverse=True
    ))
