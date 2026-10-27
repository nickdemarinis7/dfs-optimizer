from __future__ import annotations

from dataclasses import dataclass, replace

from dfs_optimizer.models import Position, Projection, Slate

from .player_context import PlayerContext, verified_player_context_ids


@dataclass(frozen=True, slots=True)
class OpportunityAssessment:
    platform_id: str
    player: str
    score: float | None
    tier: str
    reasons: tuple[str, ...]
    range_factor: float


def apply_opportunity_risk(
    slate: Slate,
    projections: tuple[Projection, ...],
    contexts: tuple[PlayerContext, ...] = (),
) -> tuple[tuple[Projection, ...], tuple[OpportunityAssessment, ...]]:
    """Grade current opportunity and conservatively widen weak-role outcomes.

    Median points remain untouched here: recent usage and depth-chart changes
    already affect the core forecast. This layer prevents an uncertain role
    from retaining an unrealistically safe floor or bust probability.
    """
    players = {player.platform_id: player for player in slate.players}
    context_by_id = {item.platform_id: item for item in contexts}
    verified_ids = verified_player_context_ids(contexts)
    unavailable = {"IR", "O", "OUT", "INACTIVE", "INJURED RESERVE"}
    healthy_leaders = {
        (player.team, player.primary_position)
        for player in slate.players
        if (context := context_by_id.get(player.platform_id)) is not None
        and context.depth_chart_position == 1
        and context.active is not False
        and (
            context.injury_status or player.status or ""
        ).strip().upper() not in unavailable
    }
    output = []
    assessments = []
    for projection in projections:
        player_id = projection.platform_id or ""
        player = players.get(player_id)
        if player is None or player.primary_position in {Position.DST, Position.K}:
            output.append(projection)
            continue
        context = context_by_id.get(player_id)
        evidence = (
            projection.opportunity_stability is not None
            or projection.bust_probability is not None
            or projection.floor is not None
            or player_id in verified_ids
        )
        if not evidence:
            output.append(projection)
            assessments.append(OpportunityAssessment(
                player_id, player.name, None, "Unrated",
                ("insufficient current-opportunity evidence",), 1.0,
            ))
            continue

        score = 65.0
        reasons = []
        sample_size = projection.sample_size
        limited_sample = sample_size is not None and sample_size < 3
        if sample_size == 1:
            score -= 20
            reasons.append("one-game sample cannot establish a reliable role")
        elif sample_size == 2:
            score -= 10
            reasons.append("two-game sample provides limited role evidence")
        prop_count = projection.prop_market_count or 0
        if prop_count >= 2:
            score += 8
            reasons.append(f"active betting markets confirm role ({prop_count} props)")
        elif projection.prop_coverage_checked and prop_count == 0:
            score -= 12
            reasons.append("no player props in a well-covered game")
        stability = projection.opportunity_stability
        if stability is not None:
            if stability < .25:
                score -= 35
                reasons.append("sharp recent usage or snap-share decline")
            elif stability < .50:
                score -= 22
                reasons.append("meaningful recent opportunity decline")
            elif stability < .70:
                score -= 10
                reasons.append("uneven recent opportunity")
            elif stability >= .85:
                score += 10
                reasons.append("recent opportunity has held")

        status = (
            (context.injury_status if context and context.injury_status else None)
            or player.status or ""
        ).strip().upper()
        depth = context.depth_chart_position if context else None
        expected_role = (
            (context.expected_role or "").strip().casefold() if context else ""
        )
        practice = (
            (context.practice_participation or "").strip().upper()
            if context else ""
        )
        recent_return = (
            projection.recent_return_games is not None
            and projection.recent_return_games <= 2
            and expected_role not in {"expanded", "normal"}
        )
        if recent_return:
            score -= 15
            reasons.append(
                f"game {projection.recent_return_games} after a multi-game absence"
            )
        if expected_role == "expanded":
            score += 12
            reasons.append("confirmed expanded pre-lock role")
        elif expected_role == "normal":
            reasons.append("confirmed normal pre-lock role")
        elif expected_role == "committee":
            score -= 12
            reasons.append("confirmed committee pre-lock role")
        elif expected_role == "limited":
            score -= 30
            reasons.append("confirmed limited or backup pre-lock role")
        if status in unavailable or (context is not None and context.active is False):
            score = 0
            reasons.append("currently unavailable")
        elif status in {"D", "DOUBTFUL", "Q", "QUESTIONABLE"}:
            score -= 12
            reasons.append(f"{status.lower()} availability")
        if expected_role not in {"expanded", "normal"}:
            if practice in {"DNP", "DID NOT PARTICIPATE"}:
                score -= 15
                reasons.append("did not practice before lock")
            elif practice in {"LIMITED", "LIMITED PARTICIPATION"}:
                score -= 10
                reasons.append("limited practice before lock")
        if depth is not None and expected_role not in {"expanded", "normal"}:
            leader_confirmed = (player.team, player.primary_position) in healthy_leaders
            if player.primary_position == Position.TE and depth >= 2 and leader_confirmed:
                score -= 22
                reasons.append(f"TE{depth} on current depth chart")
            elif player.primary_position == Position.RB and depth >= 3 and leader_confirmed:
                score -= 25
                reasons.append(f"RB{depth} on current depth chart")
            elif player.primary_position == Position.WR and depth >= 4 and leader_confirmed:
                score -= 25
                reasons.append(f"WR{depth} on current depth chart")
            elif player.primary_position == Position.QB and depth >= 2 and leader_confirmed:
                score -= 35
                reasons.append(f"QB{depth} on current depth chart")
            elif depth == 1:
                score += 8
                reasons.append("listed first on current depth chart")
        if player_id in verified_ids:
            score += 5
            reasons.append("current role checked")

        bust = projection.bust_probability
        # A one- or two-game sample can mechanically produce a zero bust rate
        # and a perfectly tight range. Do not reward those artifacts as proof
        # of a safe weekly role.
        if bust is not None:
            if bust >= .60:
                score -= 18
                reasons.append("high modeled bust probability")
            elif bust >= .45:
                score -= 10
                reasons.append("elevated modeled bust probability")
            elif bust <= .25 and not limited_sample:
                score += 5
                reasons.append("low modeled bust probability")
        if projection.floor is not None and projection.projected_points > 0:
            if projection.floor <= projection.projected_points * .15:
                score -= 12
                reasons.append("near-zero modeled floor")

        score = round(min(100.0, max(0.0, score)), 1)
        tier = "Strong" if score >= 75 else "Usable" if score >= 55 else "Watch" if score >= 40 else "Fragile"
        factor = .50 if tier == "Fragile" else .75 if tier == "Watch" else 1.0

        def lower(value, multiplier, *, at_least_median=False):
            if value is None:
                return None
            adjusted = value * multiplier
            return max(projection.projected_points, adjusted) if at_least_median else adjusted

        adjusted_bust = bust
        missing_props = projection.prop_coverage_checked and prop_count == 0
        if expected_role not in {"expanded", "normal"} and missing_props:
            if practice in {"DNP", "DID NOT PARTICIPATE"}:
                adjusted_bust = max(adjusted_bust or 0, .55)
            elif practice in {"LIMITED", "LIMITED PARTICIPATION"}:
                adjusted_bust = max(adjusted_bust or 0, .45)
        if recent_return:
            adjusted_bust = max(adjusted_bust or 0, .50)
        if tier == "Fragile":
            adjusted_bust = max(bust or 0, .65)
        elif tier == "Watch":
            adjusted_bust = max(bust or 0, .45)
        adjusted_p90 = lower(
            projection.p90, .90 if tier == "Fragile" else 1.0,
            at_least_median=True,
        )
        adjusted_p75 = lower(
            projection.p75,
            .95 if tier in {"Fragile", "Watch"} else 1.0,
            at_least_median=True,
        )
        if adjusted_p75 is not None and adjusted_p90 is not None:
            adjusted_p75 = min(adjusted_p75, adjusted_p90)
        return_factor = .75 if recent_return else 1.0
        updated = replace(
            projection,
            floor=lower(projection.floor, factor * return_factor),
            p10=lower(projection.p10, factor * return_factor),
            p25=lower(
                projection.p25,
                (.60 if tier == "Fragile" else factor) * return_factor,
            ),
            p75=adjusted_p75,
            p90=adjusted_p90,
            ceiling=lower(projection.ceiling, .90 if tier == "Fragile" else 1.0, at_least_median=True),
            bust_probability=adjusted_bust,
        )
        output.append(updated)
        assessments.append(OpportunityAssessment(
            player_id, player.name, score, tier,
            tuple(dict.fromkeys(reasons)) or ("baseline opportunity evidence",),
            factor,
        ))
    return tuple(output), tuple(assessments)
