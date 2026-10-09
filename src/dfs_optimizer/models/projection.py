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
    p10: float | None = None
    p25: float | None = None
    p75: float | None = None
    p90: float | None = None
    bust_probability: float | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("projection name cannot be empty")
        if not self.team:
            raise ValueError(f"projection team cannot be empty for {self.name}")
        if self.floor is not None and self.ceiling is not None and self.floor > self.ceiling:
            raise ValueError(f"floor cannot exceed ceiling for {self.name}")
        if self.projected_ownership is not None and not 0 <= self.projected_ownership <= 100:
            raise ValueError(f"projected ownership must be between 0 and 100 for {self.name}")
        percentiles = tuple(
            value for value in (self.p10, self.p25, self.p75, self.p90)
            if value is not None
        )
        if any(value < 0 for value in percentiles):
            raise ValueError(f"outcome percentiles cannot be negative for {self.name}")
        if len(percentiles) == 4 and not (
            self.p10 <= self.p25 <= self.projected_points <= self.p75 <= self.p90
        ):
            raise ValueError(f"outcome percentiles are not ordered for {self.name}")
        if self.bust_probability is not None and not 0 <= self.bust_probability <= 1:
            raise ValueError(f"bust probability must be between 0 and 1 for {self.name}")
