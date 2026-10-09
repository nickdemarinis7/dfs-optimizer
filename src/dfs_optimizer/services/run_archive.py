from __future__ import annotations

import csv
import io
import json
import zipfile
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from dfs_optimizer.exporters import lineups_csv_text


def build_run_archive(
    slate,
    projections,
    lineups,
    settings: dict,
    salary_content: bytes | None = None,
    *,
    run_id: str | None = None,
    run_label: str | None = None,
    created_at: datetime | None = None,
    projection_built_at: datetime | None = None,
) -> bytes:
    created = created_at or datetime.now(timezone.utc)
    slate_id = hashlib.sha256(
        "|".join((
            slate.platform.value,
            slate.contest_format.value,
            *sorted(slate.games),
        )).encode()
    ).hexdigest()[:16]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        manifest = {
            "run_id": run_id,
            "run_label": run_label,
            "slate_id": slate_id,
            "created_at_utc": created.isoformat(),
            "projection_built_at_utc": (
                projection_built_at.isoformat() if projection_built_at else None
            ),
            "salary_source": slate.source_name,
            "platform": slate.platform.value,
            "contest_format": slate.contest_format.value,
            "projection_count": len(projections),
            "lineup_count": len(lineups),
            "settings": settings,
        }
        archive.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
        if salary_content is not None:
            archive.writestr(f"salary/{Path(slate.source_name).name}", salary_content)
        archive.writestr("lineups.csv", lineups_csv_text(lineups, slate.platform))
        projection_output = io.StringIO(newline="")
        writer = csv.writer(projection_output)
        writer.writerow((
            "name", "team", "platform_id", "projected_points", "floor", "ceiling",
            "projected_ownership", "p10", "p25", "p75", "p90", "bust_probability",
        ))
        for item in projections:
            writer.writerow((
                item.name, item.team, item.platform_id or "", item.projected_points,
                item.floor, item.ceiling, item.projected_ownership,
                item.p10, item.p25, item.p75, item.p90, item.bust_probability,
            ))
        archive.writestr("projections.csv", projection_output.getvalue())
    return output.getvalue()


def save_run_archive(
    content: bytes,
    slate,
    directory: str | Path = "data/runs",
    created_at: datetime | None = None,
    run_id: str | None = None,
) -> Path:
    """Persist a generated run with a sortable, collision-resistant name."""
    timestamp = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    root = Path(directory).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    stem = run_id or (
        f"{timestamp:%Y%m%dT%H%M%SZ}-"
        f"{slate.platform.value}-{slate.contest_format.value}"
    )
    destination = root / f"{stem}.zip"
    suffix = 2
    while destination.exists():
        destination = root / f"{stem}-{suffix}.zip"
        suffix += 1
    destination.write_bytes(content)
    return destination
