from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from dfs_optimizer.importers import (
    DefenseProjectionImportError,
    ProjectionImportError,
    SalaryImportError,
    StatProjectionImportError,
    import_defense_projections_csv,
    import_projections_csv,
    import_salary_csv,
    import_stat_projections_csv,
    match_projections,
)
from dfs_optimizer.models import ContestFormat
from dfs_optimizer.optimization import (
    LineupOptimizationError,
    optimize_classic_lineup,
    optimize_single_game_lineup,
)
from dfs_optimizer.projections import (
    build_platform_average_projections,
    build_stat_based_projections,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import an NFL DFS salary slate")
    parser.add_argument("salaries", type=Path, help="DraftKings or FanDuel salary CSV")
    projection_source = parser.add_mutually_exclusive_group()
    projection_source.add_argument(
        "--projections", type=Path, help="projection CSV used to optimize a lineup"
    )
    projection_source.add_argument(
        "--baseline",
        action="store_true",
        help="use platform fantasy averages as a development-only baseline",
    )
    projection_source.add_argument(
        "--stat-projections",
        type=Path,
        help="platform-neutral offensive expected-stat CSV",
    )
    parser.add_argument(
        "--defense-projections",
        type=Path,
        help="team defense expected-stat CSV (used with --stat-projections)",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        slate = import_salary_csv(args.salaries)
    except (SalaryImportError, ProjectionImportError, LineupOptimizationError) as exc:
        print(f"Error: {exc}")
        return 2

    positions = Counter(player.primary_position.value for player in slate.players)
    print(f"Platform: {slate.platform.value}")
    print(f"Format: {slate.contest_format.value}")
    print(f"Players: {len(slate.players)}")
    print(f"Teams: {len(slate.teams)}")
    print(f"Games: {len(slate.games)}")
    print("Positions: " + ", ".join(f"{key}={positions[key]}" for key in sorted(positions)))
    if args.defense_projections and not args.stat_projections:
        print("Error: --defense-projections requires --stat-projections")
        return 2
    if args.stat_projections and not args.defense_projections:
        print("Error: --stat-projections requires --defense-projections")
        return 2
    if args.projections or args.baseline or args.stat_projections:
        try:
            if args.projections:
                projections = import_projections_csv(args.projections)
            elif args.stat_projections:
                offense = import_stat_projections_csv(args.stat_projections)
                defenses = import_defense_projections_csv(args.defense_projections)
                projections = build_stat_based_projections(slate, offense, defenses)
            else:
                projections = build_platform_average_projections(slate)
            matches = match_projections(slate, projections)
            lineup = (
                optimize_single_game_lineup(slate, matches)
                if slate.contest_format == ContestFormat.SINGLE_GAME
                else optimize_classic_lineup(slate, matches)
            )
        except (
            DefenseProjectionImportError,
            ProjectionImportError,
            StatProjectionImportError,
            LineupOptimizationError,
        ) as exc:
            print(f"Error: {exc}")
            return 2
        print()
        if args.baseline:
            print("BASELINE ONLY: using historical platform averages, not forecasts")
        print("Optimized lineup")
        for entry in lineup.entries:
            salary = getattr(entry, "salary", entry.player.salary)
            points = getattr(entry, "projected_points", entry.projection.projected_points)
            print(
                f"{entry.slot:4}  {entry.player.name:28} "
                f"{entry.player.team:3}  ${salary:>5,}  "
                f"{points:>5.2f} pts"
            )
        print(
            f"Total: ${lineup.salary:,} / ${lineup.salary_cap:,}  "
            f"({lineup.projected_points:.2f} projected points)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
