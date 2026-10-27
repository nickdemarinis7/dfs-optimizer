from __future__ import annotations

from dataclasses import replace

from dfs_optimizer.models import Projection, Slate, Sport

from .player_context import PlayerContext, verified_player_context_ids


def apply_projection_confidence(
    slate: Slate,
    projections: tuple[Projection, ...],
    contexts: tuple[PlayerContext, ...] = (),
    *,
    context_age_minutes: float | None = None,
) -> tuple[Projection, ...]:
    """Attach an auditable confidence score without changing point forecasts."""
    verified_ids = verified_player_context_ids(contexts)
    context_by_id = {item.platform_id: item for item in contexts}
    output = []
    for projection in projections:
        evidence = any(value is not None for value in (
            projection.sample_size,
            projection.opportunity_stability,
            projection.data_age_periods,
            projection.recent_return_games,
            projection.floor,
            projection.ceiling,
            projection.bust_probability,
        ))
        if not evidence:
            output.append(replace(
                projection,
                confidence_score=None,
                confidence_tier="Unrated",
                confidence_reasons=("insufficient confidence metadata",),
            ))
            continue

        score = 50.0
        reasons = list(projection.confidence_reasons)
        if projection.sample_size is not None:
            if projection.sample_size >= 4:
                score += 15
                reasons.append(f"{projection.sample_size}-game sample")
            elif projection.sample_size >= 2:
                score += 5
                reasons.append(f"limited {projection.sample_size}-game sample")
            else:
                score -= 15
                reasons.append("one-game sample")
        if projection.opportunity_stability is not None:
            if projection.opportunity_stability >= .70:
                score += 10
                reasons.append("stable recent opportunity")
            elif projection.opportunity_stability < .35:
                score -= 12
                reasons.append("volatile recent opportunity")
            elif projection.opportunity_stability < .70:
                score -= 8
                reasons.append("uneven recent opportunity")
        if projection.floor is not None and projection.ceiling is not None:
            relative_range = (
                projection.ceiling - projection.floor
            ) / max(1.0, projection.projected_points)
            if (
                relative_range <= 1
                and (projection.opportunity_stability or 0) >= .70
                and (
                    projection.bust_probability is not None
                    and projection.bust_probability <= .35
                )
            ):
                score += 8
                reasons.append("tight outcome range")
            elif relative_range > 2:
                score -= 10
                reasons.append("wide outcome range")
        if projection.bust_probability is not None:
            if projection.bust_probability <= .25:
                score += 8
                reasons.append("low modeled bust risk")
            elif projection.bust_probability >= .55:
                score -= 15
                reasons.append("high modeled bust risk")
        if projection.data_age_periods is not None:
            if projection.data_age_periods == 0:
                score += 8
                reasons.append("latest period represented")
            elif projection.data_age_periods >= 2:
                score -= 15
                reasons.append(f"data is {projection.data_age_periods} periods old")

        context = context_by_id.get(projection.platform_id or "")
        expected_role = (
            (context.expected_role or "").strip().casefold()
            if context else ""
        )
        if (
            projection.recent_return_games is not None
            and projection.recent_return_games <= 2
            and expected_role not in {"expanded", "normal"}
        ):
            score -= 15
            reasons.append(
                f"game {projection.recent_return_games} after multi-game absence"
            )

        player_id = projection.platform_id or ""
        context = context_by_id.get(player_id)
        if player_id in verified_ids:
            score += 8
            reasons.append("current role or availability verified")
        elif slate.sport == Sport.CFB:
            score -= 10
            reasons.append("current CFB role unverified")
        if context is not None:
            status = (context.injury_status or "").strip().upper()
            practice = (context.practice_participation or "").strip().upper()
            if status in {"QUESTIONABLE", "Q", "DOUBTFUL", "D"}:
                score -= 15
                reasons.append(f"{status.lower()} availability")
            if expected_role not in {"expanded", "normal"}:
                if practice in {"DNP", "DID NOT PARTICIPATE"}:
                    score -= 15
                    reasons.append("did not practice before lock")
                elif practice in {"LIMITED", "LIMITED PARTICIPATION"}:
                    score -= 10
                    reasons.append("limited practice before lock")
            if (context.depth_chart_position or 0) >= 3:
                score -= 10
                reasons.append(f"depth position {context.depth_chart_position}")
        if context_age_minutes is not None and contexts:
            if context_age_minutes <= 30:
                score += 3
                reasons.append("fresh pre-lock context")
            elif context_age_minutes > 120:
                score -= 10
                reasons.append("stale pre-lock context")

        # Confidence describes how dependable the forecast is, not merely how
        # much supporting data exists. A high modeled bust rate or unresolved
        # availability question cannot truthfully produce a High label.
        if (
            projection.bust_probability is not None
            and projection.bust_probability >= .45
        ):
            score = min(score, 74.9)
            reasons.append("confidence capped by modeled bust risk")
        if context is not None and (
            (context.injury_status or "").strip().upper()
            in {"QUESTIONABLE", "Q", "DOUBTFUL", "D"}
        ):
            score = min(score, 74.9)
            reasons.append("confidence capped by unresolved availability")
        if context is not None and expected_role not in {"expanded", "normal"} and (
            (context.practice_participation or "").strip().upper()
            in {"DNP", "DID NOT PARTICIPATE", "LIMITED", "LIMITED PARTICIPATION"}
        ):
            score = min(score, 74.9)
            reasons.append("confidence capped by uncertain workload")

        score = round(min(100.0, max(0.0, score)), 1)
        tier = "High" if score >= 75 else "Medium" if score >= 55 else "Low"
        output.append(replace(
            projection,
            confidence_score=score,
            confidence_tier=tier,
            confidence_reasons=tuple(reasons) or ("baseline model evidence",),
        ))
    return tuple(output)
