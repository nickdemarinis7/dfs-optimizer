from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from dfs_optimizer.models import ContestFormat, Position, Projection, Slate, Sport
from dfs_optimizer.rules import classic_rules_for, single_game_rules_for
from .risk import suggest_default_excluded_player_ids
from .player_context import PlayerContext

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
    salary_loaded_at: datetime | None = None,
    player_context: tuple[PlayerContext, ...] = (),
    player_context_built_at: datetime | None = None,
    prop_checked_at: datetime | None = None,
    prop_players_matched: int = 0,
    now: datetime | None = None,
) -> PreflightReport:
    """Independently validate the artifacts that will be submitted."""
    findings = list(audit_lineups(slate, lineups))
    passed: list[str] = []
    rules = (
        classic_rules_for(slate.platform, slate.sport)
        if slate.contest_format.value == "classic"
        else single_game_rules_for(slate.platform)
    )
    current_players = {player.platform_id: player for player in slate.players}
    current_ids = set(current_players)

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
        expected_salary = 0
        if slate.contest_format == ContestFormat.CLASSIC:
            slots = {slot.name: slot for slot in rules.slots}
            expected_slots = Counter(slot.name for slot in rules.slots)
            actual_slots = Counter(entry.slot for entry in lineup.entries)
            if actual_slots != expected_slots:
                structure_valid = False
                findings.append(AuditFinding(
                    "ERROR", "roster_slots",
                    f"Lineup {number} does not contain the required roster slots.",
                ))
            for entry in lineup.entries:
                current_player = current_players.get(entry.player.platform_id)
                if current_player is None:
                    continue
                expected_salary += current_player.salary
                slot = slots.get(entry.slot)
                if slot is None or not slot.accepts(current_player.primary_position):
                    structure_valid = False
                    findings.append(AuditFinding(
                        "ERROR", "slot_eligibility",
                        f"Lineup {number}: {current_player.name} is not eligible for "
                        f"the {entry.slot} slot.",
                    ))
        else:
            multiplier_entries = []
            for entry in lineup.entries:
                current_player = current_players.get(entry.player.platform_id)
                if current_player is None:
                    continue
                point_multiplier = getattr(entry, "point_multiplier", 1.0)
                if point_multiplier > 1:
                    multiplier_entries.append(entry)
                    expected_salary += (
                        current_player.multiplier_salary or current_player.salary
                    )
                    if (
                        entry.slot != rules.multiplier_slot
                        or point_multiplier != rules.multiplier
                    ):
                        structure_valid = False
                        findings.append(AuditFinding(
                            "ERROR", "multiplier_slot",
                            f"Lineup {number}: the multiplier entry is not a valid "
                            f"{rules.multiplier_slot} selection.",
                        ))
                else:
                    expected_salary += current_player.salary
                    if point_multiplier != 1 or not entry.slot.startswith("FLEX"):
                        structure_valid = False
                        findings.append(AuditFinding(
                            "ERROR", "flex_slot",
                            f"Lineup {number}: {current_player.name} is not assigned "
                            "to a valid FLEX slot.",
                        ))
            if len(multiplier_entries) != 1:
                structure_valid = False
                findings.append(AuditFinding(
                    "ERROR", "multiplier_count",
                    f"Lineup {number} has {len(multiplier_entries)} multiplier entries; "
                    "expected exactly one.",
                ))
        if lineup.salary != expected_salary:
            structure_valid = False
            findings.append(AuditFinding(
                "ERROR", "salary_total",
                f"Lineup {number} reports ${lineup.salary:,}, but its players cost "
                f"${expected_salary:,}.",
            ))
        if expected_salary > rules.salary_cap:
            structure_valid = False
            findings.append(AuditFinding(
                "ERROR", "salary_cap",
                f"Lineup {number}'s players exceed the ${rules.salary_cap:,} salary cap.",
            ))
        if len({entry.player.team for entry in lineup.entries}) < rules.minimum_teams:
            structure_valid = False
            findings.append(AuditFinding(
                "ERROR", "minimum_teams",
                f"Lineup {number} does not include at least {rules.minimum_teams} teams.",
            ))
        maximum_players_per_team = getattr(rules, "maximum_players_per_team", None)
        if maximum_players_per_team is not None:
            team_counts = Counter(entry.player.team for entry in lineup.entries)
            over_limit = [
                team for team, count in team_counts.items()
                if count > maximum_players_per_team
            ]
            if over_limit:
                structure_valid = False
                findings.append(AuditFinding(
                    "ERROR", "maximum_players_per_team",
                    f"Lineup {number} exceeds the {maximum_players_per_team}-player "
                    f"team limit for: {', '.join(sorted(over_limit))}.",
                ))
        minimum_games = getattr(rules, "minimum_games", 0)
        if minimum_games and len(
            {entry.player.game for entry in lineup.entries}
        ) < minimum_games:
            structure_valid = False
            findings.append(AuditFinding(
                "ERROR", "minimum_games",
                f"Lineup {number} does not include at least {minimum_games} games.",
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
        passed.append(
            "Roster sizes, player IDs, teams, games, salaries, and projections are valid"
        )

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

    if salary_loaded_at is not None:
        loaded_at = salary_loaded_at
        if loaded_at.tzinfo is None:
            loaded_at = loaded_at.replace(tzinfo=timezone.utc)
        salary_current_time = now or datetime.now(timezone.utc)
        salary_age = max(
            0.0, (salary_current_time - loaded_at).total_seconds() / 3600
        )
        if salary_age > 12:
            findings.append(AuditFinding(
                "WARNING", "stale_salary_file",
                f"The salary and player-status file was loaded {salary_age:.1f} hours ago. Reload it before lock to capture current availability.",
            ))
        else:
            passed.append(f"Salary and status file is fresh ({salary_age:.1f} hours old)")

    if slate.sport == Sport.NFL and player_context_built_at is None:
        findings.append(AuditFinding(
            "WARNING", "player_context_time_unknown",
            "Live injury and depth-chart check time is unavailable. Refresh player news before lock.",
        ))
    elif slate.sport == Sport.NFL:
        checked_at = player_context_built_at
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        context_current_time = now or datetime.now(timezone.utc)
        context_age = max(
            0.0, (context_current_time - checked_at).total_seconds() / 3600
        )
        if context_age > .5:
            findings.append(AuditFinding(
                "WARNING", "stale_player_context",
                f"Player news was checked {context_age:.1f} hours ago. Refresh it before lock.",
            ))
        else:
            passed.append(
                f"Injury and depth-chart check is fresh ({context_age * 60:.0f} minutes old)"
            )

    if slate.sport == Sport.NFL and slate.contest_format == ContestFormat.SINGLE_GAME:
        prop_now = now or datetime.now(timezone.utc)
        if prop_checked_at is None:
            findings.append(AuditFinding(
                "WARNING", "prop_context_missing",
                "Betting-market role confirmation was not run for this Showdown slate. "
                "Refresh betting-market roles before lock when the Odds API is available.",
            ))
        else:
            checked_at = prop_checked_at
            if checked_at.tzinfo is None:
                checked_at = checked_at.replace(tzinfo=timezone.utc)
            prop_age = max(0.0, (prop_now - checked_at).total_seconds() / 3600)
            if prop_age > 1:
                findings.append(AuditFinding(
                    "WARNING", "stale_prop_context",
                    f"Betting-market roles were checked {prop_age:.1f} hours ago. "
                    "Refresh them before lock.",
                ))
            elif prop_players_matched < 5:
                findings.append(AuditFinding(
                    "WARNING", "thin_prop_context",
                    f"Betting markets matched only {prop_players_matched} players. "
                    "Treat role confirmation as incomplete.",
                ))
            else:
                passed.append(
                    f"Betting-market roles are fresh for {prop_players_matched} players"
                )

    role_risks = suggest_default_excluded_player_ids(
        slate, projections, player_context
    )
    selected_ids = {
        entry.player.platform_id for lineup in lineups for entry in lineup.entries
    }
    exposure_counts = Counter(
        entry.player.platform_id for lineup in lineups for entry in lineup.entries
    )
    players_by_id = {player.platform_id: player for player in slate.players}
    context_by_id = {item.platform_id: item for item in player_context}
    unavailable_statuses = {"IR", "O", "OUT", "INACTIVE", "INJURED RESERVE"}
    questionable_statuses = {"Q", "QUESTIONABLE", "D", "DOUBTFUL"}
    selected_unmatched = []
    selected_questionable = []
    selected_unavailable = []
    for player_id in sorted(selected_ids):
        player = players_by_id[player_id]
        if player.primary_position == Position.DST:
            continue
        context = context_by_id.get(player_id)
        if context is None:
            salary_status = (player.status or "").strip().upper()
            if salary_status in unavailable_statuses:
                selected_unavailable.append(player.name)
            elif salary_status in questionable_statuses:
                selected_questionable.append(player.name)
            else:
                selected_unmatched.append(player.name)
            continue
        context_status = (context.injury_status or "").strip().upper()
        final_status_reported = context_status in {"ACTIVE", "INACTIVE", "OUT"}
        status = (
            context_status
            if context_status
            else (player.status or "").strip().upper()
        )
        if context.active is False or status in unavailable_statuses:
            selected_unavailable.append(player.name)
        elif status in questionable_statuses and not final_status_reported:
            selected_questionable.append(player.name)
    if selected_unavailable:
        findings.append(AuditFinding(
            "ERROR", "selected_player_unavailable",
            "Selected players are marked unavailable: "
            + ", ".join(selected_unavailable) + ". Regenerate before submission.",
        ))
    if selected_questionable:
        findings.append(AuditFinding(
            "WARNING", "selected_player_questionable",
            "Selected players still need a final availability check: "
            + ", ".join(selected_questionable) + ".",
        ))
    if selected_unmatched:
        findings.append(AuditFinding(
            "WARNING", "selected_player_context_unmatched",
            "No current injury/depth context matched these selected players: "
            + ", ".join(selected_unmatched) + ". Confirm them manually before submission.",
        ))
    if not (selected_unavailable or selected_questionable or selected_unmatched):
        passed.append("Every selected player has current, non-questionable availability context")
    for player_id in sorted(role_risks & selected_ids):
        player = players_by_id[player_id]
        if (player.status or "").strip().upper() not in {"IR", "O", "OUT"}:
            findings.append(AuditFinding(
                "WARNING", "backup_quarterback",
                f"{player.name} appears to be a subordinate same-team quarterback and was manually restored to the player pool.",
            ))

    for player_id, count in sorted(exposure_counts.items()):
        player = players_by_id[player_id]
        context = context_by_id.get(player_id)
        if context is None or count < 2:
            continue
        expected_role = (context.expected_role or "").strip().casefold()
        depth = context.depth_chart_position or 0
        subordinate = (
            player.primary_position == Position.TE and depth >= 2
        ) or (
            player.primary_position in {Position.RB, Position.WR} and depth >= 3
        )
        if subordinate and expected_role not in {"expanded", "normal"}:
            findings.append(AuditFinding(
                "WARNING", "subordinate_skill_exposure",
                f"{player.name} is depth {depth} and appears in {count} lineups. "
                "Confirm that the player's current role supports this exposure.",
            ))
        if expected_role == "limited":
            findings.append(AuditFinding(
                "WARNING", "limited_role_exposure",
                f"{player.name} has a confirmed limited-role report and appears in "
                f"{count} lineups. Reduce exposure or update the report before submission.",
            ))

    for context in player_context:
        expected_role = (context.expected_role or "").strip().casefold()
        status = (context.injury_status or "").strip().upper()
        if expected_role in {"expanded", "normal"} and (
            context.active is False or status in unavailable_statuses
        ):
            player = players_by_id.get(context.platform_id)
            if player is not None:
                findings.append(AuditFinding(
                    "ERROR", "role_report_availability_conflict",
                    f"{player.name} has a {expected_role} role report but is currently "
                    "marked unavailable. Clear or correct the report before submission.",
                ))

    return PreflightReport(tuple(findings), tuple(passed))
