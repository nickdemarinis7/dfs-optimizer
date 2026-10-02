from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime, timezone

from dfs_optimizer.exporters import lineups_csv_text


def build_run_archive(slate, projections, lineups, settings: dict) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        manifest = {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "salary_source": slate.source_name,
            "platform": slate.platform.value,
            "contest_format": slate.contest_format.value,
            "projection_count": len(projections),
            "lineup_count": len(lineups),
            "settings": settings,
        }
        archive.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
        archive.writestr("lineups.csv", lineups_csv_text(lineups, slate.platform))
        projection_output = io.StringIO(newline="")
        writer = csv.writer(projection_output)
        writer.writerow(("name", "team", "platform_id", "projected_points", "floor", "ceiling", "projected_ownership"))
        for item in projections:
            writer.writerow((item.name, item.team, item.platform_id or "", item.projected_points, item.floor, item.ceiling, item.projected_ownership))
        archive.writestr("projections.csv", projection_output.getvalue())
    return output.getvalue()
