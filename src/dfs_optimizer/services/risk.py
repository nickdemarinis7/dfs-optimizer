from __future__ import annotations

from dfs_optimizer.models import ContestFormat, Position, Projection, Slate, Sport
from .player_context import PlayerContext
from .opportunity import apply_opportunity_risk


UNAVAILABLE_STATUSES = frozenset({"IR", "O", "OUT"})


def trusted_showdown_core_ids(
    slate: Slate,
    projections: tuple[Projection, ...],
    contexts: tuple[PlayerContext, ...] = (),
    opportunity_assessments=(),
) -> frozenset[str]:
    """Return players safe to exceed a normal Showdown portfolio cap.

    Quarterbacks need a Strong current-opportunity grade. Skill players also
    need stable recent usage or an explicit normal/expanded pre-lock report.
    This prevents an injury returner with an old productive sample—or a
    volatile promoted reserve—from becoming a universal core merely because a
    small player pool forced the optimizer to relax its global exposure cap.
    """
    if slate.contest_format != ContestFormat.SINGLE_GAME:
        return frozenset()
    assessments = {
        item.platform_id: item for item in opportunity_assessments
    }
    context_by_id = {item.platform_id: item for item in contexts}
    players = {item.platform_id: item for item in slate.players}
    trusted = set()
    for projection in projections:
        player_id = projection.platform_id or ""
        player = players.get(player_id)
        assessment = assessments.get(player_id)
        if (
            player is None
            or assessment is None
            or assessment.tier != "Strong"
            or (projection.bust_probability or 0) >= .45
        ):
            continue
        context = context_by_id.get(player_id)
        expected_role = (
            (context.expected_role or "").strip().casefold()
            if context else ""
        )
        if (
            player.primary_position == Position.QB
            or (projection.opportunity_stability or 0) >= .70
            or expected_role in {"expanded", "normal"}
        ):
            trusted.add(player_id)
    return frozenset(trusted)


def suggest_player_exposure_limits(
    slate: Slate,
    projections: tuple[Projection, ...],
    contexts: tuple[PlayerContext, ...] = (),
    opportunity_assessments=(),
) -> dict[str, float]:
    """Return portfolio-size-aware caps for volatile CFB Classic players.

    The fractions are converted to integer appearance limits by the optimizer,
    so a 50% cap permits one appearance in a three-lineup portfolio, five in
    ten, and ten in twenty. Stronger availability or role concerns receive a
    25% cap. Definitively unavailable players are handled by default excludes.
    """
    if slate.contest_format != ContestFormat.CLASSIC:
        return {}
    if slate.sport == Sport.NFL:
        assessments = tuple(opportunity_assessments)
        if not assessments:
            _, assessments = apply_opportunity_risk(slate, projections, contexts)
        return {
            item.platform_id: .34 if item.tier == "Fragile" else .50
            for item in assessments
            if item.tier in {"Fragile", "Watch"}
        }
    if slate.sport != Sport.CFB:
        return {}
    projection_by_id = {
        item.platform_id: item for item in projections if item.platform_id
    }
    context_by_id = {item.platform_id: item for item in contexts}
    limits: dict[str, float] = {}
    for player in slate.players:
        if player.primary_position not in {Position.RB, Position.WR, Position.TE}:
            continue
        projection = projection_by_id.get(player.platform_id)
        if projection is None:
            continue
        context = context_by_id.get(player.platform_id)
        status = (
            (context.injury_status if context else None) or player.status or ""
        ).strip().upper()
        depth = context.depth_chart_position if context else None
        limit: float | None = None
        if status in {"DOUBTFUL", "D"} or (depth is not None and depth >= 3):
            limit = .25
        elif status in {"QUESTIONABLE", "Q"} or (
            player.primary_position == Position.TE
            and depth is not None
            and depth >= 2
        ):
            limit = .34
        if (projection.bust_probability or 0) >= .55:
            limit = min(limit or 1, .34)
        elif (projection.bust_probability or 0) >= .44:
            limit = min(limit or 1, .50)
        if (
            projection.floor is not None
            and projection.projected_points > 0
            and projection.floor <= projection.projected_points * .20
        ):
            limit = min(limit or 1, .34)
        if context and context.verified_projection is not None:
            limit = min(limit or 1, .34)
        if projection.confidence_score is not None:
            if projection.confidence_score < 40:
                limit = min(limit or 1, .25)
            elif projection.confidence_score < 55:
                limit = min(limit or 1, .34)
        if limit is not None:
            limits[player.platform_id] = limit
    return limits


def suggest_default_excluded_player_ids(
    slate: Slate,
    projections: tuple[Projection, ...],
    contexts: tuple[PlayerContext, ...] = (),
) -> frozenset[str]:
    """Suggest players who should not enter a lineup without an override.

    Definitively unavailable players are always suggested. A quarterback is
    also suggested when another available QB on the same team has both a
    materially stronger projection and salary signal. This prevents prior
    spot-start production from making a current backup look like cheap value.
    """
    by_id = {
        projection.platform_id: projection
        for projection in projections
        if projection.platform_id
    }
    unavailable = {
        player.platform_id
        for player in slate.players
        if (player.status or "").strip().upper() in UNAVAILABLE_STATUSES
    }
    context_by_id = {item.platform_id: item for item in contexts}
    unavailable.update(
        player.platform_id
        for player in slate.players
        if (context := context_by_id.get(player.platform_id)) is not None
        and (
            context.active is False
            or (context.injury_status or "").strip().upper()
            in {"IR", "O", "OUT", "INJURED RESERVE"}
        )
    )
    quarterbacks_by_team: dict[str, list] = {}
    for player in slate.players:
        if (
            player.primary_position == Position.QB
            and player.platform_id in by_id
            and player.platform_id not in unavailable
        ):
            quarterbacks_by_team.setdefault(player.team, []).append(player)

    backups: set[str] = set()
    for quarterbacks in quarterbacks_by_team.values():
        if len(quarterbacks) < 2:
            continue
        starter = max(
            quarterbacks,
            key=lambda player: (
                by_id[player.platform_id].projected_points,
                player.salary,
            ),
        )
        starter_projection = by_id[starter.platform_id].projected_points
        if starter_projection < 8:
            continue
        for quarterback in quarterbacks:
            if quarterback.platform_id == starter.platform_id:
                continue
            projection_ratio = (
                by_id[quarterback.platform_id].projected_points / starter_projection
            )
            salary_ratio = quarterback.salary / starter.salary
            if projection_ratio < .65 and salary_ratio < .80:
                backups.add(quarterback.platform_id)

    for team, quarterbacks in quarterbacks_by_team.items():
        has_available_qb1 = any(
            context_by_id.get(player.platform_id)
            and context_by_id[player.platform_id].depth_chart_position == 1
            and player.platform_id not in unavailable
            for player in quarterbacks
        )
        if has_available_qb1:
            backups.update(
                player.platform_id
                for player in quarterbacks
                if context_by_id.get(player.platform_id)
                and (context_by_id[player.platform_id].depth_chart_position or 1) > 1
                and (context_by_id[player.platform_id].expected_role or "")
                .strip().casefold() not in {"expanded", "normal"}
            )

    extreme_showdown_punts: set[str] = set()
    if slate.contest_format == ContestFormat.SINGLE_GAME:
        extreme_showdown_punts.update(
            player.platform_id
            for player in slate.players
            if player.primary_position in {Position.RB, Position.WR, Position.TE}
            and (projection := by_id.get(player.platform_id)) is not None
            and projection.projected_points < 5
            and projection.floor is not None
            and projection.floor <= .5
            and projection.p25 is not None
            and projection.p25 <= .5
            and (
                (
                    (projection.bust_probability or 0) >= .70
                    and (context := context_by_id.get(player.platform_id)) is not None
                    and (context.depth_chart_position or 0) >= 3
                )
                or (
                    # A sub-1.5 median with no meaningful lower-quartile
                    # outcome is a no-role profile even when the external
                    # depth chart does not match the player. This catches
                    # practice-squad and deep-reserve darts without removing
                    # demonstrated salary-relief options.
                    projection.projected_points < 1.5
                    and (projection.bust_probability or 0) >= .50
                )
            )
        )

    return frozenset(unavailable | backups | extreme_showdown_punts)


def suggest_max_once_player_ids(
    slate: Slate,
    projections: tuple[Projection, ...],
    contexts: tuple[PlayerContext, ...] = (),
) -> frozenset[str]:
    """Identify fragile values that should not become a multi-lineup core.

    This is deliberately conservative: a player is suggested when a historical
    floor near zero is paired with a usable but sub-10-point median, or when an
    NFL skill player has both a sub-10-point median and a high modeled bust
    probability. Projections without either risk signal remain available.
    Users can remove any suggestion in the builder.
    """
    by_id = {
        projection.platform_id: projection
        for projection in projections
        if projection.platform_id
    }
    suggestions = {
        player.platform_id
        for player in slate.players
        if (projection := by_id.get(player.platform_id)) is not None
        and projection.floor is not None
        and projection.floor <= 1
        and 2 <= projection.projected_points < 10
    }
    if slate.sport == Sport.NFL:
        suggestions.update(
            player.platform_id
            for player in slate.players
            if player.primary_position in {Position.RB, Position.WR, Position.TE}
            and (projection := by_id.get(player.platform_id)) is not None
            and 2 <= projection.projected_points < 10
            and (projection.bust_probability or 0) >= .45
        )
    if slate.sport == Sport.CFB:
        suggestions.update(
            player.platform_id
            for player in slate.players
            if player.primary_position in {Position.RB, Position.WR, Position.TE}
            and (projection := by_id.get(player.platform_id)) is not None
            and (
                (projection.bust_probability or 0) >= .44
                or (
                    projection.projected_points < 15
                    and (projection.bust_probability or 0) >= .42
                )
                or (
                    projection.projected_points < 15
                    and projection.floor is not None
                    and projection.floor <= projection.projected_points * .25
                )
            )
        )
    context_by_id = {item.platform_id: item for item in contexts}
    suggestions.update(
        player.platform_id
        for player in slate.players
        if player.primary_position in {Position.RB, Position.WR, Position.TE}
        and (context := context_by_id.get(player.platform_id)) is not None
        and (context.expected_role or "").strip().casefold()
        not in {"expanded", "normal"}
        and (
            (player.primary_position == Position.TE and (context.depth_chart_position or 0) >= 2)
            or (context.depth_chart_position or 0) >= 3
        )
        and (projection := by_id.get(player.platform_id)) is not None
        and projection.projected_points < 12
        and (
            (projection.opportunity_stability or 0) < .70
            or (projection.bust_probability or 0) >= .35
            or projection.floor is None
            or projection.floor <= projection.projected_points * .40
        )
    )
    return frozenset(suggestions)
