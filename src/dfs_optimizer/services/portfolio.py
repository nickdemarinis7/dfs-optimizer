from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any

from dfs_optimizer.models import Position


@dataclass(frozen=True, slots=True)
class PortfolioDiagnostics:
    lineup_count: int
    unique_quarterbacks: int
    maximum_exposure_count: int
    average_shared_players: float | None
    maximum_shared_players: int | None
    projection_spread: float
    full_exposure_players: tuple[str, ...]
    selected_statuses: tuple[str, ...]
    projection_coverage: float

    @property
    def warnings(self) -> tuple[str, ...]:
        messages = []
        if self.lineup_count > 1 and self.unique_quarterbacks < 2:
            messages.append("All lineups use the same quarterback stack.")
        if self.lineup_count > 1 and self.full_exposure_players:
            names = ", ".join(self.full_exposure_players)
            if len(self.full_exposure_players) > 4:
                messages.append(
                    f"Core is too concentrated: {len(self.full_exposure_players)} players appear "
                    f"in all {self.lineup_count} lineups ({names})."
                )
            else:
                messages.append(f"Full-portfolio core ({self.lineup_count}/{self.lineup_count}): {names}.")
        if self.average_shared_players is not None and self.average_shared_players > 6:
            messages.append(
                f"Lineup overlap is high at {self.average_shared_players:.1f} shared players on average."
            )
        if self.projection_spread >= 8:
            messages.append(
                f"The lowest lineup projects {self.projection_spread:.1f} points below the highest."
            )
        if self.projection_coverage < 0.25:
            messages.append(
                f"Only {self.projection_coverage:.0%} of salary rows have projections."
            )
        if self.selected_statuses:
            messages.append("Selected players have injury/status flags: " + ", ".join(self.selected_statuses) + ".")
        return tuple(messages)


def analyze_portfolio(
    lineups: tuple[Any, ...],
    projected_player_count: int,
    salary_player_count: int,
) -> PortfolioDiagnostics:
    player_sets = [
        {entry.player.platform_id for entry in lineup.entries} for lineup in lineups
    ]
    overlaps = [len(left & right) for left, right in combinations(player_sets, 2)]
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    quarterbacks = set()
    statuses = set()
    for lineup in lineups:
        for entry in lineup.entries:
            player = entry.player
            counts[player.platform_id] = counts.get(player.platform_id, 0) + 1
            names[player.platform_id] = player.name
            if player.primary_position == Position.QB:
                quarterbacks.add(player.platform_id)
            if player.status:
                statuses.add(f"{player.name} ({player.status})")
    projections = [lineup.projected_points for lineup in lineups]
    maximum = max(counts.values(), default=0)
    full_exposure = tuple(
        sorted(names[player_id] for player_id, count in counts.items() if count == len(lineups))
    ) if lineups else ()
    return PortfolioDiagnostics(
        lineup_count=len(lineups),
        unique_quarterbacks=len(quarterbacks),
        maximum_exposure_count=maximum,
        average_shared_players=sum(overlaps) / len(overlaps) if overlaps else None,
        maximum_shared_players=max(overlaps) if overlaps else None,
        projection_spread=max(projections) - min(projections) if projections else 0,
        full_exposure_players=full_exposure,
        selected_statuses=tuple(sorted(statuses)),
        projection_coverage=(projected_player_count / salary_player_count if salary_player_count else 0),
    )
