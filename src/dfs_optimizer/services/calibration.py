from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def calibration_record(
    run_id: str,
    slate,
    metrics,
    evaluation_rows,
    field_size: int,
    winning_score: float,
    submitted_entries=(),
) -> dict:
    positions = {}
    for row in evaluation_rows:
        item = positions.setdefault(row.position, {"errors": [], "absolute_errors": []})
        item["errors"].append(row.error)
        item["absolute_errors"].append(row.absolute_error)
    position_metrics = {
        position: {
            "players": len(values["errors"]),
            "mae": sum(values["absolute_errors"]) / len(values["absolute_errors"]),
            "bias": sum(values["errors"]) / len(values["errors"]),
        }
        for position, values in positions.items()
    }
    best = min(submitted_entries, key=lambda item: item.rank) if submitted_entries else None
    return {
        "run_id": run_id,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform": slate.platform.value,
        "contest_format": slate.contest_format.value,
        "salary_source": slate.source_name,
        "field_size": field_size,
        "winning_score": winning_score,
        "submitted_entries": len(submitted_entries),
        "best_rank": best.rank if best else None,
        "best_top_percent": 100 * best.rank / field_size if best else None,
        "best_score": best.score if best else None,
        "projection_metrics": {
            "matched_players": metrics.matched_players,
            "mae": metrics.mean_absolute_error,
            "rmse": metrics.root_mean_squared_error,
            "bias": metrics.mean_error,
            "correlation": metrics.correlation,
            "range_samples": metrics.range_samples,
            "interval_coverage": metrics.interval_coverage,
            "ceiling_exceed_rate": metrics.ceiling_exceed_rate,
        },
        "position_metrics": position_metrics,
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
