from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from dfs_optimizer.backtesting import import_fanduel_results


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize a FanDuel contest-results export")
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    contest = import_fanduel_results(args.results)
    scores = sorted(entry.points for entry in contest.scored_entries)
    duplicates = contest.duplicated_lineups
    print(f"Entries: {len(contest.entries):,} ({len(scores):,} scored)")
    print(f"Players: {len(contest.players)}")
    print(f"Score range: {scores[0]:.2f} - {scores[-1]:.2f}")
    for percentile in (50, 75, 90, 95, 99):
        index = min(len(scores) - 1, round((percentile / 100) * (len(scores) - 1)))
        print(f"P{percentile}: {scores[index]:.2f}")
    print(f"Unique lineups: {len(duplicates):,}")
    print(f"Most duplicated lineup: {max(duplicates.values()):,} entries")
    print("Highest ownership:")
    for player in sorted(contest.players, key=lambda item: item.drafted_percent, reverse=True)[:10]:
        print(f"  {player.name:28} {player.drafted_percent:6.2f}%  {player.fantasy_points:6.2f} pts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

