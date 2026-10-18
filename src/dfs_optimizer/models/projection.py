from __future__ import annotations

from dataclasses import dataclass
import math


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
    sample_size: int | None = None
    opportunity_stability: float | None = None
    data_age_periods: int | None = None
    confidence_score: float | None = None
    confidence_tier: str | None = None
    confidence_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("projection name cannot be empty")
        if not self.team:
            raise ValueError(f"projection team cannot be empty for {self.name}")
        numeric_values = {
            "projected_points": self.projected_points,
            "floor": self.floor,
            "ceiling": self.ceiling,
            "projected_ownership": self.projected_ownership,
            "p10": self.p10,
            "p25": self.p25,
            "p75": self.p75,
            "p90": self.p90,
            "bust_probability": self.bust_probability,
            "opportunity_stability": self.opportunity_stability,
            "confidence_score": self.confidence_score,
        }
        non_finite = [
            field for field, value in numeric_values.items()
            if value is not None and not math.isfinite(value)
        ]
        if non_finite:
            raise ValueError(
                f"projection values must be finite for {self.name}: "
                + ", ".join(non_finite)
            )
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
        if self.sample_size is not None and self.sample_size < 0:
            raise ValueError(f"sample size cannot be negative for {self.name}")
        if self.data_age_periods is not None and self.data_age_periods < 0:
            raise ValueError(f"data age cannot be negative for {self.name}")
        if self.opportunity_stability is not None and not 0 <= self.opportunity_stability <= 1:
            raise ValueError(f"opportunity stability must be between 0 and 1 for {self.name}")
        if self.confidence_score is not None and not 0 <= self.confidence_score <= 100:
            raise ValueError(f"confidence score must be between 0 and 100 for {self.name}")
        if self.confidence_tier is not None and self.confidence_tier not in {
            "High", "Medium", "Low", "Unrated"
        }:
            raise ValueError(f"invalid confidence tier for {self.name}")
