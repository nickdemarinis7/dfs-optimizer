from __future__ import annotations

from dataclasses import dataclass

from .player import ContestFormat, Platform, Player, Sport


@dataclass(frozen=True, slots=True)
class Slate:
    platform: Platform
    contest_format: ContestFormat
    players: tuple[Player, ...]
    source_name: str
    sport: Sport = Sport.NFL

    def __post_init__(self) -> None:
        if not self.players:
            raise ValueError("slate must contain at least one player")
        ids = [player.platform_id for player in self.players]
        if len(ids) != len(set(ids)):
            raise ValueError("slate contains duplicate platform player IDs")

    @property
    def teams(self) -> frozenset[str]:
        return frozenset(player.team for player in self.players)

    @property
    def games(self) -> frozenset[str]:
        return frozenset(player.game for player in self.players)
