from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Platform(StrEnum):
    DRAFTKINGS = "draftkings"
    FANDUEL = "fanduel"


class ContestFormat(StrEnum):
    CLASSIC = "classic"
    SINGLE_GAME = "single_game"


class Sport(StrEnum):
    NFL = "nfl"
    CFB = "cfb"


class Position(StrEnum):
    QB = "QB"
    RB = "RB"
    WR = "WR"
    TE = "TE"
    DST = "DST"
    K = "K"
    FLEX = "FLEX"
    SUPER_FLEX = "S-FLEX"

    @classmethod
    def from_platform_value(cls, value: str) -> Position:
        normalized = value.strip().upper()
        if normalized in {"D", "DEF", "DST"}:
            return cls.DST
        if normalized in {"S-FLEX", "SUPER FLEX", "SUPERFLEX"}:
            return cls.SUPER_FLEX
        return cls(normalized)


@dataclass(frozen=True, slots=True)
class Player:
    platform_id: str
    name: str
    primary_position: Position
    roster_positions: tuple[Position, ...]
    salary: int
    team: str
    opponent: str
    game: str
    platform_average: float | None = None
    status: str | None = None
    injury_details: str | None = None
    multiplier_platform_id: str | None = None
    multiplier_salary: int | None = None

    def __post_init__(self) -> None:
        if not self.platform_id:
            raise ValueError("player platform_id cannot be empty")
        if not self.name:
            raise ValueError("player name cannot be empty")
        if self.salary <= 0:
            raise ValueError(f"salary must be positive for {self.name}")
        if not self.roster_positions:
            raise ValueError(f"roster positions cannot be empty for {self.name}")
