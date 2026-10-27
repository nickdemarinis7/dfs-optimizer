from __future__ import annotations

import argparse
import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dfs_optimizer.backtesting import import_player_results_content
from dfs_optimizer.importers import match_projections
from dfs_optimizer.models import ContestFormat, Platform, Position, Projection, Sport
from dfs_optimizer.optimization import (
    ClassicOptimizationSettings,
    DEFAULT_SHOWDOWN_MAX_KICKERS_AND_DEFENSES,
    LineupOptimizationError,
    SingleGameOptimizationSettings,
    generate_classic_3max_portfolio,
    generate_single_game_3max_portfolio,
    generate_single_game_lineups,
    optimize_classic_lineup,
)
from dfs_optimizer.services.player_context import PlayerContext
from dfs_optimizer.services.opportunity import apply_opportunity_risk
from dfs_optimizer.services.risk import (
    suggest_default_excluded_player_ids,
    suggest_max_once_player_ids,
    suggest_player_exposure_limits,
)
from dfs_optimizer.services.run_history import RunRecord, restore_run


@dataclass(frozen=True, slots=True)
class PortfolioResult:
    scores: tuple[float, ...]
    ranks: tuple[int, ...]
    top_percentages: tuple[float, ...]


def _normalized(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _result_text(content: bytes, filename: str) -> str:
    if Path(filename).suffix.casefold() != ".zip":
        return content.decode("utf-8-sig")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = [name for name in archive.namelist() if name.casefold().endswith(".csv")]
        if len(names) != 1:
            raise ValueError("results ZIP must contain exactly one CSV file")
        return archive.read(names[0]).decode("utf-8-sig")


def _field_scores(content: bytes, filename: str) -> tuple[float, ...]:
    rows = csv.DictReader(io.StringIO(_result_text(content, filename)))
    scores_by_entry = {}
    for row in rows:
        value = (row.get("Points") or "").strip()
        if value and value.casefold() != "null":
            scores_by_entry.setdefault(row["EntryId"], float(value))
    return tuple(scores_by_entry.values())


def score_portfolio(lineups, result_content: bytes, result_name: str) -> PortfolioResult:
    player_results = import_player_results_content(result_content, result_name)
    actual = {_normalized(item.name): item.fantasy_points for item in player_results}
    field_scores = _field_scores(result_content, result_name)
    if not field_scores:
        raise ValueError("contest standings have no scored entries")
    scores = tuple(round(sum(
        actual.get(_normalized(entry.player.name), 0.0)
        * getattr(entry, "point_multiplier", 1.0)
        for entry in lineup.entries
    ), 4) for lineup in lineups)
    ranks = tuple(1 + sum(field_score > score for field_score in field_scores) for score in scores)
    return PortfolioResult(
        scores,
        ranks,
        tuple(100 * rank / len(field_scores) for rank in ranks),
    )


def _record(path: Path, manifest: dict) -> RunRecord:
    return RunRecord(
        run_id=manifest.get("run_id") or path.stem,
        label=manifest.get("run_label") or path.stem,
        created_at=datetime.fromisoformat(manifest["created_at_utc"]),
        platform=Platform(manifest["platform"]),
        sport=Sport(manifest.get("sport", "nfl")),
        contest_format=ContestFormat(manifest["contest_format"]),
        slate_id=manifest.get("slate_id", "legacy"),
        source_name=manifest["salary_source"],
        lineup_count=int(manifest["lineup_count"]),
        projection_count=int(manifest["projection_count"]),
        path=path,
    )


def _archived_context(slate, settings: dict) -> tuple[PlayerContext, ...]:
    by_name = {_normalized(player.name): player for player in slate.players}
    contexts = []
    for item in settings.get("player_context", ()):
        player = by_name.get(_normalized(item.get("player", "")))
        if player is None:
            continue
        contexts.append(PlayerContext(
            platform_id=player.platform_id,
            depth_chart_position=item.get("depth_chart_position"),
            injury_status=item.get("injury_status"),
            practice_participation=item.get("practice_participation"),
            active=item.get("active"),
            verified_projection=item.get("verified_projection"),
            expected_role=item.get("expected_role"),
            role_note=item.get("role_note"),
            injury_reported=bool(
                item.get("injury_status") or item.get("practice_participation")
            ),
        ))
    return tuple(contexts)


def regenerate_current_portfolio(slate, projections, settings: dict):
    players = {player.platform_id: player for player in slate.players}
    ids_by_name = {_normalized(player.name): player.platform_id for player in slate.players}
    contexts = _archived_context(slate, settings)
    archived_exclusions = frozenset(
        ids_by_name[_normalized(name)]
        for name in settings.get("excluded_players", ())
        if _normalized(name) in ids_by_name
    )
    exclusions = archived_exclusions | (
        suggest_default_excluded_player_ids(slate, projections, contexts) & players.keys()
    )
    limited = (
        suggest_max_once_player_ids(slate, projections, contexts) & players.keys()
    ) - exclusions
    matches = match_projections(slate, projections)
    if slate.contest_format == ContestFormat.CLASSIC:
        _, opportunity_assessments = apply_opportunity_risk(
            slate, projections, contexts
        )
        exposure_limits = suggest_player_exposure_limits(
            slate, projections, contexts, opportunity_assessments
        )
        classic_settings = ClassicOptimizationSettings(
            excluded_player_ids=exclusions,
            limited_player_ids=limited,
            player_exposure_limits=tuple(sorted(
                (player_id, limit)
                for player_id, limit in exposure_limits.items()
                if player_id not in exclusions and player_id not in limited
            )),
            fragile_player_ids=limited,
            maximum_fragile_players=2,
            qb_stack_size=1,
            require_opponent_bring_back=True,
            ceiling_weight=.3,
            minimum_stack_projection=7,
            minimum_bring_back_projection=7,
            minimum_stack_ceiling=12,
            minimum_bring_back_ceiling=12,
            unique_primary_stacks=True,
            ownership_penalty=.01,
        )
        return generate_classic_3max_portfolio(
            slate, matches, classic_settings, candidate_count=8
        )
    fragile = frozenset(
        player_id for player_id in limited
        if players[player_id].primary_position in {Position.RB, Position.WR, Position.TE}
    )
    optimization_settings = SingleGameOptimizationSettings(
        multiplier_positions=frozenset({Position.QB, Position.RB, Position.WR, Position.TE}),
        minimum_multiplier_ceiling=18,
        maximum_multiplier_bust_probability=.45,
        minimum_quarterbacks=1,
        minimum_quarterback_projection=5,
        minimum_player_projection=.1,
        maximum_players_per_team=4,
        maximum_kickers_and_defenses=DEFAULT_SHOWDOWN_MAX_KICKERS_AND_DEFENSES,
        maximum_dst_opponents=1,
        require_multiplier_receiver_qb=True,
        ceiling_weight=.3,
        excluded_player_ids=exclusions,
        limited_player_ids=limited,
        fragile_player_ids=fragile,
        maximum_fragile_players=1,
        bust_probability_penalty=.5,
        ownership_penalty=.01,
    )
    try:
        return generate_single_game_3max_portfolio(
            slate, matches, optimization_settings
        )
    except LineupOptimizationError:
        return generate_single_game_lineups(
            slate,
            matches,
            3,
            minimum_unique_players=2,
            maximum_player_exposure=.67,
            maximum_multiplier_exposure=.34,
            settings=optimization_settings,
            lineup_ceiling_weights=(.3, .3, .7),
        )


def compare_archive(archive_path: Path, results_path: Path) -> dict:
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    record = _record(archive_path, manifest)
    slate, projections, original, _, settings = restore_run(record)
    current = regenerate_current_portfolio(slate, projections, settings)
    result_content = results_path.read_bytes()
    original_result = score_portfolio(original, result_content, results_path.name)
    current_result = score_portfolio(current, result_content, results_path.name)
    comparison = {
        "archive": str(archive_path),
        "results": str(results_path),
        "platform": slate.platform.value,
        "original": {
            "scores": original_result.scores,
            "ranks": original_result.ranks,
            "top_percentages": original_result.top_percentages,
        },
        "current": {
            "scores": current_result.scores,
            "ranks": current_result.ranks,
            "top_percentages": current_result.top_percentages,
        },
        "original_players": tuple(
            tuple(entry.player.name for entry in lineup.entries) for lineup in original
        ),
        "current_players": tuple(
            tuple(entry.player.name for entry in lineup.entries) for lineup in current
        ),
    }
    if slate.contest_format == ContestFormat.CLASSIC:
        actual_results = import_player_results_content(
            result_content, results_path.name
        )
        actual_by_name = {
            _normalized(item.name): item.fantasy_points for item in actual_results
        }
        projection_by_name = {
            _normalized(item.name): item.projected_points for item in projections
        }
        errors = [
            {
                "player": player.name,
                "projected": round(projection_by_name[_normalized(player.name)], 2),
                "actual": round(actual_by_name[_normalized(player.name)], 2),
                "error": round(
                    actual_by_name[_normalized(player.name)]
                    - projection_by_name[_normalized(player.name)],
                    2,
                ),
            }
            for player in slate.players
            if _normalized(player.name) in actual_by_name
            and _normalized(player.name) in projection_by_name
        ]
        actual_projections = tuple(
            Projection(
                name=player.name,
                team=player.team,
                projected_points=actual_by_name.get(_normalized(player.name), 0),
                platform_id=player.platform_id,
            )
            for player in slate.players
        )
        oracle = optimize_classic_lineup(
            slate,
            match_projections(slate, actual_projections),
            settings=ClassicOptimizationSettings(avoid_dst_opponents=False),
        )
        comparison["diagnostics"] = {
            "winning_score": max(_field_scores(result_content, results_path.name)),
            "legal_oracle_score": round(oracle.projected_points, 2),
            "legal_oracle_players": tuple(
                entry.player.name for entry in oracle.entries
            ),
            "largest_underprojections": sorted(
                errors, key=lambda item: item["error"], reverse=True
            )[:10],
            "largest_overprojections": sorted(
                errors, key=lambda item: item["error"]
            )[:10],
        }
    return comparison


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Regenerate an archived DFS run and score it against real standings."
    )
    parser.add_argument("archive", type=Path)
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare_archive(args.archive, args.results), indent=2))


if __name__ == "__main__":
    main()
