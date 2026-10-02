from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Mapping

from dfs_optimizer.models import ContestFormat, Platform, Player, Position, Slate


class SalaryImportError(ValueError):
    """Raised when a platform salary file cannot be recognized or parsed."""


def import_salary_csv(path: str | Path) -> Slate:
    source = Path(path)
    try:
        with source.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = set(reader.fieldnames or ())
            rows = list(reader)
    except OSError as exc:
        raise SalaryImportError(f"could not read {source}: {exc}") from exc

    if not rows:
        raise SalaryImportError(f"salary file is empty: {source}")

    if {"Name + ID", "TeamAbbrev", "Game Info"}.issubset(headers):
        roster_values = {row.get("Roster Position", "") for row in rows}
        if roster_values == {"CPT", "FLEX"}:
            return _import_draftkings_single_game(rows, source.name)
        return _import_draftkings(rows, source.name)
    if {"Id", "Nickname", "Team", "Opponent"}.issubset(headers):
        if "MVP 1.5x Salary" in headers:
            return _import_fanduel_single_game(rows, source.name)
        return _import_fanduel(rows, source.name)
    raise SalaryImportError(
        f"unrecognized salary file schema in {source}; headers were: "
        + ", ".join(sorted(header for header in headers if header))
    )


def _import_draftkings(
    rows: Iterable[Mapping[str, str]], source_name: str
) -> Slate:
    players: list[Player] = []
    for row_number, row in enumerate(rows, start=2):
        try:
            team = row["TeamAbbrev"].strip().upper()
            game = row["Game Info"].strip()
            matchup = game.split(maxsplit=1)[0]
            away, home = matchup.split("@", maxsplit=1)
            opponent = home if team == away else away
            players.append(
                Player(
                    platform_id=row["ID"].strip(),
                    name=row["Name"].strip(),
                    primary_position=Position.from_platform_value(row["Position"]),
                    roster_positions=_parse_roster_positions(row["Roster Position"]),
                    salary=_parse_salary(row["Salary"]),
                    team=team,
                    opponent=opponent,
                    game=game,
                    platform_average=_parse_optional_float(row.get("AvgPointsPerGame")),
                    status=_optional_text(row.get("Status")),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SalaryImportError(
                f"invalid DraftKings row {row_number} in {source_name}: {exc}"
            ) from exc
    return Slate(
        platform=Platform.DRAFTKINGS,
        contest_format=ContestFormat.CLASSIC,
        players=tuple(players),
        source_name=source_name,
    )


def _import_fanduel(rows: Iterable[Mapping[str, str]], source_name: str) -> Slate:
    players: list[Player] = []
    for row_number, row in enumerate(rows, start=2):
        try:
            name = row["Nickname"].strip() or " ".join(
                part.strip() for part in (row["First Name"], row["Last Name"])
            )
            players.append(
                Player(
                    platform_id=row["Id"].strip(),
                    name=name,
                    primary_position=Position.from_platform_value(row["Position"]),
                    roster_positions=_parse_roster_positions(row["Roster Position"]),
                    salary=_parse_salary(row["Salary"]),
                    team=row["Team"].strip().upper(),
                    opponent=row["Opponent"].strip().upper(),
                    game=row["Game"].strip(),
                    platform_average=_parse_optional_float(row.get("FPPG")),
                    status=_optional_text(row.get("Injury Indicator")),
                    injury_details=_optional_text(row.get("Injury Details")),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SalaryImportError(
                f"invalid FanDuel row {row_number} in {source_name}: {exc}"
            ) from exc
    return Slate(
        platform=Platform.FANDUEL,
        contest_format=ContestFormat.CLASSIC,
        players=tuple(players),
        source_name=source_name,
    )


def _import_draftkings_single_game(rows, source_name: str) -> Slate:
    grouped: dict[tuple[str, str], dict[str, Mapping[str, str]]] = {}
    for row in rows:
        grouped.setdefault((row["Name"].strip(), row["TeamAbbrev"].strip().upper()), {})[
            row["Roster Position"].strip()
        ] = row
    players = []
    for (name, team), variants in grouped.items():
        if set(variants) != {"CPT", "FLEX"}:
            raise SalaryImportError(f"DraftKings single-game player {name} lacks CPT or FLEX row")
        flex, captain = variants["FLEX"], variants["CPT"]
        game = flex["Game Info"].strip()
        away, home = game.split(maxsplit=1)[0].split("@", 1)
        players.append(Player(
            platform_id=flex["ID"].strip(), name=name,
            primary_position=Position.from_platform_value(flex["Position"]),
            roster_positions=(Position.FLEX,), salary=_parse_salary(flex["Salary"]),
            team=team, opponent=home if team == away else away, game=game,
            platform_average=_parse_optional_float(flex.get("AvgPointsPerGame")),
            status=_optional_text(flex.get("Status")),
            multiplier_platform_id=captain["ID"].strip(),
            multiplier_salary=_parse_salary(captain["Salary"]),
        ))
    return Slate(Platform.DRAFTKINGS, ContestFormat.SINGLE_GAME, tuple(players), source_name)


def _import_fanduel_single_game(rows, source_name: str) -> Slate:
    players = []
    for row_number, row in enumerate(rows, start=2):
        try:
            name = row["Nickname"].strip() or f'{row["First Name"].strip()} {row["Last Name"].strip()}'
            players.append(Player(
                platform_id=row["Id"].strip(), name=name,
                primary_position=Position.from_platform_value(row["Position"]),
                roster_positions=(Position.FLEX,), salary=_parse_salary(row["Salary"]),
                team=row["Team"].strip().upper(), opponent=row["Opponent"].strip().upper(),
                game=row["Game"].strip(), platform_average=_parse_optional_float(row.get("FPPG")),
                status=_optional_text(row.get("Injury Indicator")),
                injury_details=_optional_text(row.get("Injury Details")),
                multiplier_platform_id=row["Id"].strip(),
                multiplier_salary=_parse_salary(row["MVP 1.5x Salary"]),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            raise SalaryImportError(f"invalid FanDuel single-game row {row_number}: {exc}") from exc
    return Slate(Platform.FANDUEL, ContestFormat.SINGLE_GAME, tuple(players), source_name)


def _parse_roster_positions(value: str) -> tuple[Position, ...]:
    return tuple(Position.from_platform_value(part) for part in value.split("/") if part)


def _parse_salary(value: str) -> int:
    return int(value.strip().replace("$", "").replace(",", ""))


def _parse_optional_float(value: str | None) -> float | None:
    return float(value) if value and value.strip() else None


def _optional_text(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None
