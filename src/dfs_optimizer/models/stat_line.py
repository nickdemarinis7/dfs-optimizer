from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OffensiveStatLine:
    """One realized or simulated NFL offensive stat line.

    Yardage can be negative. Count-based fields must be non-negative. This type
    represents one outcome; expected bonus points should be obtained by scoring
    simulations, not by applying thresholds to an average yardage projection.
    """

    passing_yards: float = 0
    passing_touchdowns: float = 0
    interceptions_thrown: float = 0
    rushing_yards: float = 0
    rushing_touchdowns: float = 0
    receptions: float = 0
    receiving_yards: float = 0
    receiving_touchdowns: float = 0
    return_touchdowns: float = 0
    fumbles_lost: float = 0
    two_point_conversions: float = 0
    offensive_fumble_recovery_touchdowns: float = 0

    def __post_init__(self) -> None:
        count_fields = (
            "passing_touchdowns",
            "interceptions_thrown",
            "rushing_touchdowns",
            "receptions",
            "receiving_touchdowns",
            "return_touchdowns",
            "fumbles_lost",
            "two_point_conversions",
            "offensive_fumble_recovery_touchdowns",
        )
        for field_name in count_fields:
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} cannot be negative")


@dataclass(frozen=True, slots=True)
class ProjectedOffensiveStats:
    """Expected offensive volume plus probabilities of yardage bonuses."""

    passing_yards: float = 0
    passing_touchdowns: float = 0
    interceptions_thrown: float = 0
    rushing_yards: float = 0
    rushing_touchdowns: float = 0
    receptions: float = 0
    receiving_yards: float = 0
    receiving_touchdowns: float = 0
    return_touchdowns: float = 0
    fumbles_lost: float = 0
    two_point_conversions: float = 0
    offensive_fumble_recovery_touchdowns: float = 0
    passing_bonus_probability: float = 0
    rushing_bonus_probability: float = 0
    receiving_bonus_probability: float = 0

    def __post_init__(self) -> None:
        nonnegative_fields = (
            "passing_touchdowns",
            "interceptions_thrown",
            "rushing_touchdowns",
            "receptions",
            "receiving_touchdowns",
            "return_touchdowns",
            "fumbles_lost",
            "two_point_conversions",
            "offensive_fumble_recovery_touchdowns",
        )
        for field_name in nonnegative_fields:
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} cannot be negative")
        probability_fields = (
            "passing_bonus_probability",
            "rushing_bonus_probability",
            "receiving_bonus_probability",
        )
        for field_name in probability_fields:
            value = getattr(self, field_name)
            if not 0 <= value <= 1:
                raise ValueError(f"{field_name} must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class DefenseStatLine:
    sacks: float = 0
    interceptions: float = 0
    fumble_recoveries: float = 0
    return_touchdowns: float = 0
    safeties: float = 0
    blocked_kicks: float = 0
    extra_point_returns: float = 0
    points_allowed: int = 0

    def __post_init__(self) -> None:
        for field_name in (
            "sacks",
            "interceptions",
            "fumble_recoveries",
            "return_touchdowns",
            "safeties",
            "blocked_kicks",
            "extra_point_returns",
            "points_allowed",
        ):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} cannot be negative")


@dataclass(frozen=True, slots=True)
class ProjectedDefenseStats:
    sacks: float = 0
    interceptions: float = 0
    fumble_recoveries: float = 0
    return_touchdowns: float = 0
    safeties: float = 0
    blocked_kicks: float = 0
    extra_point_returns: float = 0
    probability_allow_0: float = 0
    probability_allow_1_to_6: float = 0
    probability_allow_7_to_13: float = 0
    probability_allow_14_to_20: float = 0
    probability_allow_21_to_27: float = 0
    probability_allow_28_to_34: float = 0
    probability_allow_35_plus: float = 0

    def __post_init__(self) -> None:
        event_fields = (
            "sacks",
            "interceptions",
            "fumble_recoveries",
            "return_touchdowns",
            "safeties",
            "blocked_kicks",
            "extra_point_returns",
        )
        for field_name in event_fields:
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} cannot be negative")
        probabilities = self.points_allowed_probabilities
        if any(not 0 <= value <= 1 for value in probabilities):
            raise ValueError("points-allowed probabilities must be between 0 and 1")
        if abs(sum(probabilities) - 1.0) > 1e-6:
            raise ValueError("points-allowed probabilities must sum to 1")

    @property
    def points_allowed_probabilities(self) -> tuple[float, ...]:
        return (
            self.probability_allow_0,
            self.probability_allow_1_to_6,
            self.probability_allow_7_to_13,
            self.probability_allow_14_to_20,
            self.probability_allow_21_to_27,
            self.probability_allow_28_to_34,
            self.probability_allow_35_plus,
        )


@dataclass(frozen=True, slots=True)
class ProjectedKickerStats:
    field_goals_0_to_39: float = 0
    field_goals_40_to_49: float = 0
    field_goals_50_plus: float = 0
    extra_points: float = 0

    def __post_init__(self) -> None:
        if min(self.field_goals_0_to_39, self.field_goals_40_to_49, self.field_goals_50_plus, self.extra_points) < 0:
            raise ValueError("projected kicker stats cannot be negative")
