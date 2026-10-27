from __future__ import annotations

from dataclasses import dataclass

from dfs_optimizer.backtesting import PlayerResult, ProjectionMetrics, evaluate_projections


@dataclass(frozen=True, slots=True)
class WeeklyContextExperimentResult:
    treatment_metrics: ProjectionMetrics
    control_metrics: ProjectionMetrics
    treatment_lineup_scores: tuple[float, ...]
    control_lineup_scores: tuple[float, ...]

    @property
    def mae_change(self) -> float:
        """Treatment MAE minus control MAE; negative means context helped."""
        return (
            self.treatment_metrics.mean_absolute_error
            - self.control_metrics.mean_absolute_error
        )

    @property
    def average_lineup_score_change(self) -> float:
        return _average(self.treatment_lineup_scores) - _average(
            self.control_lineup_scores
        )

    @property
    def best_lineup_score_change(self) -> float:
        return max(self.treatment_lineup_scores) - max(self.control_lineup_scores)


def evaluate_weekly_context_experiment(
    treatment_projections,
    treatment_lineups,
    control_projections,
    control_lineups,
    actuals: tuple[PlayerResult, ...],
    *,
    excluded_player_names: frozenset[str] = frozenset(),
) -> WeeklyContextExperimentResult:
    """Grade paired portfolios generated with and without weekly context."""
    treatment_scores = _score_lineups(treatment_lineups, actuals)
    control_scores = _score_lineups(control_lineups, actuals)
    if not treatment_scores or not control_scores:
        raise ValueError("the A/B portfolios could not be matched to player results")
    return WeeklyContextExperimentResult(
        treatment_metrics=evaluate_projections(
            tuple(treatment_projections), actuals,
            excluded_player_names=excluded_player_names,
        ),
        control_metrics=evaluate_projections(
            tuple(control_projections), actuals,
            excluded_player_names=excluded_player_names,
        ),
        treatment_lineup_scores=treatment_scores,
        control_lineup_scores=control_scores,
    )


def _score_lineups(lineups, actuals: tuple[PlayerResult, ...]) -> tuple[float, ...]:
    actual_by_name = {_normalize(item.name): item.fantasy_points for item in actuals}
    scores = []
    for lineup in lineups:
        score = 0.0
        for entry in lineup.entries:
            try:
                points = actual_by_name[_normalize(entry.player.name)]
            except KeyError:
                break
            score += points * getattr(entry, "point_multiplier", 1.0)
        else:
            scores.append(score)
    return tuple(scores)


def _normalize(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _average(values: tuple[float, ...]) -> float:
    return sum(values) / len(values)
