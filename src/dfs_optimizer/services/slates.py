from __future__ import annotations

import tempfile
import csv
import re
from collections import defaultdict
from datetime import datetime
from dataclasses import replace
from pathlib import Path

from dfs_optimizer.importers import SalaryImportError, import_salary_csv
from dfs_optimizer.models import Slate


_SCHEDULE_TEAM_ALIASES = {"JAC": "JAX", "LAR": "LA"}


def _normalize_matchup(matchup: str) -> str:
    raw_matchup = matchup.strip().upper().split()[0]
    if "@" not in raw_matchup:
        return raw_matchup
    away, home = raw_matchup.split("@", 1)
    return (
        f"{_SCHEDULE_TEAM_ALIASES.get(away, away)}@"
        f"{_SCHEDULE_TEAM_ALIASES.get(home, home)}"
    )


def _slate_gameday(slate: Slate) -> str | None:
    for game in slate.games:
        match = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", game)
        if match:
            return datetime.strptime(match.group(1), "%m/%d/%Y").date().isoformat()
    match = re.search(
        r"\b(\d{4}) EDT-(\d{2}) EDT-(\d{2})\b", slate.source_name
    )
    return "-".join(match.groups()) if match else None


def infer_slate_period(
    slate: Slate,
    games_file: str | Path,
) -> tuple[int, int, int, int] | None:
    """Return season, week, matched games, and slate games when schedule matching is unambiguous."""
    source = Path(games_file)
    if not source.is_file():
        return None
    grouped: dict[tuple[int, int], set[str]] = defaultdict(set)
    gamedays: dict[tuple[int, int], set[str]] = defaultdict(set)
    with source.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("game_type") != "REG":
                continue
            try:
                period = (int(row["season"]), int(row["week"]))
            except (KeyError, TypeError, ValueError):
                continue
            grouped[period].add(_normalize_matchup(
                f"{row.get('away_team', '')}@{row.get('home_team', '')}"
            ))
            if row.get("gameday"):
                gamedays[period].add(row["gameday"])
    slate_games = {_normalize_matchup(game) for game in slate.games}
    slate_gameday = _slate_gameday(slate)
    scores = [
        (len(slate_games & games), period)
        for period, games in grouped.items()
        if slate_gameday is None or slate_gameday in gamedays[period]
    ]
    if not scores:
        return None
    best_score = max(score for score, _ in scores)
    best = [period for score, period in scores if score == best_score]
    if best_score < max(1, len(slate_games) // 2) or len(best) != 1:
        return None
    season, week = best[0]
    return season, week, best_score, len(slate_games)


def discover_salary_files(directory: str | Path) -> tuple[tuple[Path, Slate], ...]:
    root = Path(directory).expanduser()
    if not root.is_dir():
        return ()
    discovered = []
    for path in sorted(root.glob("*.csv"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            discovered.append((path, import_salary_csv(path)))
        except SalaryImportError:
            continue
    return tuple(discovered)


def load_uploaded_salary_file(filename: str, content: bytes) -> Slate:
    suffix = Path(filename).suffix or ".csv"
    with tempfile.NamedTemporaryFile(suffix=suffix) as handle:
        handle.write(content)
        handle.flush()
        slate = import_salary_csv(handle.name)
    # The temporary path changes on every Streamlit rerun. Preserve the upload's
    # stable name so the slate hash, cached projections, and generated lineups do not.
    return replace(slate, source_name=Path(filename).name)
