from __future__ import annotations

from dataclasses import dataclass

from dfs_optimizer.models import ContestFormat, Platform, Position


@dataclass(frozen=True, slots=True)
class RosterSlot:
    name: str
    eligible_positions: frozenset[Position]

    def accepts(self, position: Position) -> bool:
        return position in self.eligible_positions


@dataclass(frozen=True, slots=True)
class RosterRules:
    platform: Platform
    contest_format: ContestFormat
    salary_cap: int
    slots: tuple[RosterSlot, ...]
    minimum_teams: int = 2

    @property
    def lineup_size(self) -> int:
        return len(self.slots)


def _slot(name: str, *positions: Position) -> RosterSlot:
    return RosterSlot(name=name, eligible_positions=frozenset(positions))


_CLASSIC_SLOTS = (
    _slot("QB", Position.QB),
    _slot("RB1", Position.RB),
    _slot("RB2", Position.RB),
    _slot("WR1", Position.WR),
    _slot("WR2", Position.WR),
    _slot("WR3", Position.WR),
    _slot("TE", Position.TE),
    _slot("FLEX", Position.RB, Position.WR, Position.TE),
    _slot("DST", Position.DST),
)


CLASSIC_RULES: dict[Platform, RosterRules] = {
    Platform.DRAFTKINGS: RosterRules(
        platform=Platform.DRAFTKINGS,
        contest_format=ContestFormat.CLASSIC,
        salary_cap=50_000,
        slots=_CLASSIC_SLOTS,
    ),
    Platform.FANDUEL: RosterRules(
        platform=Platform.FANDUEL,
        contest_format=ContestFormat.CLASSIC,
        salary_cap=60_000,
        slots=_CLASSIC_SLOTS,
    ),
}


def classic_rules_for(platform: Platform) -> RosterRules:
    return CLASSIC_RULES[platform]

