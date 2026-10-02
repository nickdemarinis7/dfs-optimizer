from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any

from dfs_optimizer.models import Position, Slate


BLOCKING_STATUSES = frozenset({"IR", "O", "OUT"})


@dataclass(frozen=True, slots=True)
class AuditFinding:
    severity: str
    code: str
    message: str


def audit_lineups(
    slate: Slate,
    lineups: tuple[Any, ...],
    maximum_core_size: int = 4,
    maximum_pair_overlap: int = 6,
    minimum_stack_ceiling: float = 0,
    minimum_bring_back_ceiling: float = 0,
) -> tuple[AuditFinding, ...]:
    findings = []
    current_players = {player.platform_id: player for player in slate.players}
    appearances: dict[str, int] = {}
    names = {}
    player_sets = []
    for number, lineup in enumerate(lineups, 1):
        player_sets.append({entry.player.platform_id for entry in lineup.entries})
        for entry in lineup.entries:
            player = entry.player
            appearances[player.platform_id] = appearances.get(player.platform_id, 0) + 1
            names[player.platform_id] = player.name
            current_player = current_players.get(player.platform_id, player)
            status = (current_player.status or "").strip().upper()
            if status in BLOCKING_STATUSES:
                findings.append(AuditFinding("ERROR", "unavailable_player", f"Lineup {number}: {player.name} is {status}."))
            elif status:
                findings.append(AuditFinding("WARNING", "player_status", f"Lineup {number}: {player.name} has status {status}."))
        quarterback = next((entry for entry in lineup.entries if entry.player.primary_position == Position.QB), None)
        if quarterback is not None:
            stack = [entry for entry in lineup.entries if entry.player.team == quarterback.player.team and entry.player.primary_position in {Position.WR, Position.TE}]
            bring_backs = [entry for entry in lineup.entries if entry.player.team == quarterback.player.opponent and entry.player.primary_position in {Position.RB, Position.WR, Position.TE}]
            if stack and max((entry.projection.ceiling or entry.projection.projected_points) for entry in stack) < minimum_stack_ceiling:
                findings.append(AuditFinding("ERROR", "low_stack_ceiling", f"Lineup {number}: no stack partner clears the {minimum_stack_ceiling:g}-point ceiling minimum."))
            if bring_backs and max((entry.projection.ceiling or entry.projection.projected_points) for entry in bring_backs) < minimum_bring_back_ceiling:
                findings.append(AuditFinding("ERROR", "low_bringback_ceiling", f"Lineup {number}: no bring-back clears the {minimum_bring_back_ceiling:g}-point ceiling minimum."))
    if lineups:
        core = sorted(names[player_id] for player_id, count in appearances.items() if count == len(lineups))
        if len(core) > maximum_core_size:
            findings.append(AuditFinding("WARNING", "large_core", f"{len(core)} players appear in every lineup: {', '.join(core)}."))
    for (left_index, left), (right_index, right) in combinations(enumerate(player_sets, 1), 2):
        overlap = len(left & right)
        if overlap > maximum_pair_overlap:
            findings.append(AuditFinding("WARNING", "high_overlap", f"Lineups {left_index} and {right_index} share {overlap} players."))
    return tuple(findings)
