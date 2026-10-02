from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from dfs_optimizer.models import Projection, Slate
from dfs_optimizer.rules import classic_rules_for, single_game_rules_for

from .audit import AuditFinding, audit_lineups


@dataclass(frozen=True, slots=True)
class PreflightReport:
    findings: tuple[AuditFinding, ...]
    passed: tuple[str, ...]

    @property
    def blocking(self) -> bool:
        return any(item.severity == "ERROR" for item in self.findings)


def preflight_lineups(
    slate: Slate,
    projections: tuple[Projection, ...],
    lineups: tuple[Any, ...],
    *,
    expected_lineups: int | None = None,
    projection_built_at: datetime | None = None,
    now: datetime | None = None,
) -> PreflightReport:
    """Independently validate the artifacts that will be submitted."""
    findings = list(audit_lineups(slate, lineups))
    passed: list[str] = []
    rules = (
        classic_rules_for(slate.platform)
        if slate.contest_format.value == "classic"
        else single_game_rules_for(slate.platform)
    )
    current_ids = {player.platform_id for player in slate.players}

    if expected_lineups is not None and len(lineups) != expected_lineups:
        findings.append(AuditFinding(
            "ERROR", "lineup_count",
            f"Expected {expected_lineups} lineups but generated {len(lineups)}.",
        ))
    else:
        passed.append(f"All {len(lineups)} requested lineups were generated")

    structure_valid = True
    for number, lineup in enumerate(lineups, 1):
        ids = [entry.player.platform_id for entry in lineup.entries]
        if len(ids) != rules.lineup_size:
            structure_valid = False
            findings.append(AuditFinding(
                "ERROR", "lineup_size",
                f"Lineup {number} has {len(ids)} players; expected {rules.lineup_size}.",
            ))
        if len(ids) != len(set(ids)):
            structure_valid = False
            findings.append(AuditFinding(
                "ERROR", "duplicate_player",
                f"Lineup {number} contains the same player more than once.",
            ))
        missing = set(ids) - current_ids
        if missing:
            structure_valid = False
            findings.append(AuditFinding(
                "ERROR", "player_not_on_slate",
                f"Lineup {number} contains player IDs absent from the current slate: {', '.join(sorted(missing))}.",
            ))
        if lineup.salary > rules.salary_cap:
            structure_valid = False
            findings.append(AuditFinding(
                "ERROR", "salary_cap",
                f"Lineup {number} exceeds the ${rules.salary_cap:,} salary cap.",
            ))
        if len({entry.player.team for entry in lineup.entries}) < rules.minimum_teams:
            structure_valid = False
            findings.append(AuditFinding(
                "ERROR", "minimum_teams",
                f"Lineup {number} does not include at least {rules.minimum_teams} teams.",
            ))
        for entry in lineup.entries:
            if entry.projection not in projections:
                structure_valid = False
                findings.append(AuditFinding(
                    "ERROR", "missing_projection",
                    f"Lineup {number}: {entry.player.name} is missing from the projection snapshot.",
                ))
            if entry.projection.projected_points <= 0:
                structure_valid = False
                findings.append(AuditFinding(
                    "ERROR", "nonpositive_projection",
                    f"Lineup {number}: {entry.player.name} has a non-positive projection.",
                ))
    if structure_valid:
        passed.append("Roster sizes, player IDs, teams, salaries, and projections are valid")

    if projection_built_at is None:
        findings.append(AuditFinding(
            "WARNING", "projection_time_unknown",
            "Projection build time is unavailable; rebuild before lock if these are not fresh.",
        ))
    else:
        current_time = now or datetime.now(timezone.utc)
        built_at = projection_built_at
        if built_at.tzinfo is None:
            built_at = built_at.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (current_time - built_at).total_seconds() / 3600)
        if age_hours > 6:
            findings.append(AuditFinding(
                "WARNING", "stale_projections",
                f"Projections were built {age_hours:.1f} hours ago. Refresh them after the latest news.",
            ))
        else:
            passed.append(f"Projection snapshot is fresh ({age_hours:.1f} hours old)")

    return PreflightReport(tuple(findings), tuple(passed))
