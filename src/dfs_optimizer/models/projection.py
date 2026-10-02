from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Projection:
    name: str
    team: str
    projected_points: float
    platform_id: str | None = None
    floor: float | None = None
    ceiling: float | None = None
    projected_ownership: float | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("projection name cannot be empty")
        if not self.team:
            raise ValueError(f"projection team cannot be empty for {self.name}")
        if self.floor is not None and self.ceiling is not None and self.floor > self.ceiling:
            raise ValueError(f"floor cannot exceed ceiling for {self.name}")
        if self.projected_ownership is not None and not 0 <= self.projected_ownership <= 100:
            raise ValueError(f"projected ownership must be between 0 and 100 for {self.name}")
