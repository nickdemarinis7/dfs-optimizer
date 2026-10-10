from __future__ import annotations

import argparse
from pathlib import Path

from dfs_optimizer.data_sources.nflverse import download_nflverse_season
from dfs_optimizer.exporters import export_lineups_csv
from dfs_optimizer.importers import import_salary_csv, match_projections
from dfs_optimizer.models import ContestFormat
from dfs_optimizer.optimization import (
    ClassicOptimizationSettings,
    generate_classic_lineups,
    generate_single_game_lineups,
)
from dfs_optimizer.projections import (
    apply_pregame_context,
    build_stat_based_projections,
    forecast_from_nflverse,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an NFL lineup from nflverse history")
    parser.add_argument("salaries", type=Path)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--cache", type=Path, default=Path("data/cache"))
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--lineups", type=int, default=1)
    parser.add_argument("--minimum-unique", type=int, default=1)
    parser.add_argument("--qb-stack", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--bring-back", action="store_true")
    parser.add_argument("--allow-dst-conflicts", action="store_true")
    parser.add_argument("--lock", action="append", default=[], metavar="PLAYER_ID")
    parser.add_argument("--exclude", action="append", default=[], metavar="PLAYER_ID")
    parser.add_argument(
        "--max-exposure",
        type=float,
        default=100,
        metavar="PERCENT",
        help="maximum exposure for unlocked players (0-100)",
    )
    parser.add_argument(
        "--max-qb-exposure",
        type=float,
        default=100,
        metavar="PERCENT",
        help="maximum quarterback exposure (0-100)",
    )
    parser.add_argument("--max-dst-exposure", type=float, default=100, metavar="PERCENT")
    parser.add_argument("--min-stack-projection", type=float, default=0, metavar="POINTS")
    parser.add_argument("--min-bring-back-projection", type=float, default=0, metavar="POINTS")
    parser.add_argument("--min-stack-ceiling", type=float, default=0, metavar="POINTS")
    parser.add_argument("--min-bring-back-ceiling", type=float, default=0, metavar="POINTS")
    parser.add_argument("--unique-primary-stacks", action="store_true")
    parser.add_argument("--output", type=Path, help="write generated roster columns to CSV")
    parser.add_argument("--max-multiplier-exposure", type=float, default=100, metavar="PERCENT")
    args = parser.parse_args()

    seasons = (args.season - 1, args.season)
    if args.download:
        for season in seasons:
            download_nflverse_season(season, args.cache)
    player_files = tuple(args.cache / f"players_{season}.csv" for season in seasons)
    team_files = tuple(args.cache / f"teams_{season}.csv" for season in seasons)
    games_file = args.cache / "games.csv"
    missing = [path for path in (*player_files, *team_files, games_file) if not path.exists()]
    if missing:
        parser.error("missing cached data files: " + ", ".join(str(path) for path in missing))

    slate = import_salary_csv(args.salaries)
    offense, defenses = forecast_from_nflverse(
        slate, player_files, team_files, games_file, args.season, args.week
    )
    offense, defenses = apply_pregame_context(
        slate, offense, defenses, team_files, games_file, args.season, args.week
    )
    projections = build_stat_based_projections(slate, offense, defenses)
    settings = ClassicOptimizationSettings(
        locked_player_ids=frozenset(args.lock),
        excluded_player_ids=frozenset(args.exclude),
        qb_stack_size=args.qb_stack,
        require_opponent_bring_back=args.bring_back,
        avoid_dst_opponents=not args.allow_dst_conflicts,
        minimum_stack_projection=args.min_stack_projection,
        minimum_bring_back_projection=args.min_bring_back_projection,
        minimum_stack_ceiling=args.min_stack_ceiling,
        minimum_bring_back_ceiling=args.min_bring_back_ceiling,
        unique_primary_stacks=args.unique_primary_stacks,
    )
    matches = match_projections(slate, projections)
    if slate.contest_format == ContestFormat.SINGLE_GAME:
        lineups = generate_single_game_lineups(
            slate, matches, args.lineups, args.minimum_unique,
            args.max_exposure / 100, args.max_multiplier_exposure / 100,
        )
    else:
        lineups = generate_classic_lineups(
            slate, matches, count=args.lineups,
            minimum_unique_players=args.minimum_unique, settings=settings,
            maximum_player_exposure=args.max_exposure / 100,
            maximum_qb_exposure=args.max_qb_exposure / 100,
            maximum_dst_exposure=args.max_dst_exposure / 100,
        )
    print(f"Historical forecast coverage: {len(projections)} / {len(slate.players)}")
    for number, lineup in enumerate(lineups, start=1):
        print(f"\nLineup {number}")
        for entry in lineup.entries:
            print(f"{entry.slot:4}  {entry.player.name:28} {entry.player.team:3}  ${entry.player.salary:>5,}  {entry.projection.projected_points:>5.2f}")
        print(f"Total: ${lineup.salary:,} / ${lineup.salary_cap:,} ({lineup.projected_points:.2f} projected points)")
    if args.output:
        destination = export_lineups_csv(lineups, slate.platform, args.output)
        print(f"\nExported {len(lineups)} lineups to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
