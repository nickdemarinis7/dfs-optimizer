from __future__ import annotations

from dataclasses import dataclass

from dfs_optimizer.models import (
    DefenseStatLine,
    OffensiveStatLine,
    Platform,
    ProjectedDefenseStats,
    ProjectedKickerStats,
    ProjectedOffensiveStats,
)


@dataclass(frozen=True, slots=True)
class NFLScoringRules:
    platform: Platform
    points_per_reception: float
    points_per_passing_yard: float = 0.04
    points_per_passing_touchdown: float = 4
    points_per_interception_thrown: float = -1
    points_per_rushing_yard: float = 0.1
    points_per_rushing_touchdown: float = 6
    points_per_receiving_yard: float = 0.1
    points_per_receiving_touchdown: float = 6
    passing_bonus_threshold: float = 300
    rushing_bonus_threshold: float = 100
    receiving_bonus_threshold: float = 100
    yardage_bonus_points: float = 3
    points_per_return_touchdown: float = 6
    points_per_fumble_lost: float = -1
    points_per_two_point_conversion: float = 2
    points_per_offensive_fumble_recovery_touchdown: float = 6
    points_per_sack: float = 1
    points_per_defensive_interception: float = 2
    points_per_fumble_recovery: float = 2
    points_per_defensive_return_touchdown: float = 6
    points_per_safety: float = 2
    points_per_blocked_kick: float = 2
    points_per_extra_point_return: float = 2
    points_allowed_scores: tuple[float, ...] = (10, 7, 4, 1, 0, -1, -4)

    def score_offense(self, stats: OffensiveStatLine) -> float:
        points = (
            stats.passing_yards * self.points_per_passing_yard
            + stats.passing_touchdowns * self.points_per_passing_touchdown
            + stats.interceptions_thrown * self.points_per_interception_thrown
            + stats.rushing_yards * self.points_per_rushing_yard
            + stats.rushing_touchdowns * self.points_per_rushing_touchdown
            + stats.receptions * self.points_per_reception
            + stats.receiving_yards * self.points_per_receiving_yard
            + stats.receiving_touchdowns * self.points_per_receiving_touchdown
            + stats.return_touchdowns * self.points_per_return_touchdown
            + stats.fumbles_lost * self.points_per_fumble_lost
            + stats.two_point_conversions * self.points_per_two_point_conversion
            + stats.offensive_fumble_recovery_touchdowns
            * self.points_per_offensive_fumble_recovery_touchdown
        )
        if stats.passing_yards >= self.passing_bonus_threshold:
            points += self.yardage_bonus_points
        if stats.rushing_yards >= self.rushing_bonus_threshold:
            points += self.yardage_bonus_points
        if stats.receiving_yards >= self.receiving_bonus_threshold:
            points += self.yardage_bonus_points
        return points

    def project_offense(self, stats: ProjectedOffensiveStats) -> float:
        """Convert expected stats to expected fantasy points.

        Bonus probabilities are supplied independently so a 295-yard mean does
        not incorrectly imply either zero or three expected bonus points.
        """
        return (
            stats.passing_yards * self.points_per_passing_yard
            + stats.passing_touchdowns * self.points_per_passing_touchdown
            + stats.interceptions_thrown * self.points_per_interception_thrown
            + stats.rushing_yards * self.points_per_rushing_yard
            + stats.rushing_touchdowns * self.points_per_rushing_touchdown
            + stats.receptions * self.points_per_reception
            + stats.receiving_yards * self.points_per_receiving_yard
            + stats.receiving_touchdowns * self.points_per_receiving_touchdown
            + stats.return_touchdowns * self.points_per_return_touchdown
            + stats.fumbles_lost * self.points_per_fumble_lost
            + stats.two_point_conversions * self.points_per_two_point_conversion
            + stats.offensive_fumble_recovery_touchdowns
            * self.points_per_offensive_fumble_recovery_touchdown
            + stats.passing_bonus_probability * self.yardage_bonus_points
            + stats.rushing_bonus_probability * self.yardage_bonus_points
            + stats.receiving_bonus_probability * self.yardage_bonus_points
        )

    def score_defense(self, stats: DefenseStatLine) -> float:
        return self._defense_event_points(stats) + self._points_allowed_score(
            stats.points_allowed
        )

    def project_defense(self, stats: ProjectedDefenseStats) -> float:
        event_points = self._defense_event_points(stats)
        expected_points_allowed_score = sum(
            probability * score
            for probability, score in zip(
                stats.points_allowed_probabilities,
                self.points_allowed_scores,
                strict=True,
            )
        )
        return event_points + expected_points_allowed_score

    def _defense_event_points(
        self, stats: DefenseStatLine | ProjectedDefenseStats
    ) -> float:
        return (
            stats.sacks * self.points_per_sack
            + stats.interceptions * self.points_per_defensive_interception
            + stats.fumble_recoveries * self.points_per_fumble_recovery
            + stats.return_touchdowns * self.points_per_defensive_return_touchdown
            + stats.safeties * self.points_per_safety
            + stats.blocked_kicks * self.points_per_blocked_kick
            + stats.extra_point_returns * self.points_per_extra_point_return
        )

    def _points_allowed_score(self, points_allowed: int) -> float:
        if points_allowed == 0:
            return self.points_allowed_scores[0]
        if points_allowed <= 6:
            return self.points_allowed_scores[1]
        if points_allowed <= 13:
            return self.points_allowed_scores[2]
        if points_allowed <= 20:
            return self.points_allowed_scores[3]
        if points_allowed <= 27:
            return self.points_allowed_scores[4]
        if points_allowed <= 34:
            return self.points_allowed_scores[5]
        return self.points_allowed_scores[6]

    def project_kicker(self, stats: ProjectedKickerStats) -> float:
        return (
            stats.field_goals_0_to_39 * 3
            + stats.field_goals_40_to_49 * 4
            + stats.field_goals_50_plus * 5
            + stats.extra_points
        )


NFL_SCORING_RULES: dict[Platform, NFLScoringRules] = {
    Platform.DRAFTKINGS: NFLScoringRules(
        platform=Platform.DRAFTKINGS,
        points_per_reception=1.0,
        points_per_fumble_lost=-1,
    ),
    Platform.FANDUEL: NFLScoringRules(
        platform=Platform.FANDUEL,
        points_per_reception=0.5,
        points_per_fumble_lost=-2,
    ),
}


def nfl_scoring_for(platform: Platform) -> NFLScoringRules:
    return NFL_SCORING_RULES[platform]
