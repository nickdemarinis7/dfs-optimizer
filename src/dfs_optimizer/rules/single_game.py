from __future__ import annotations

from dataclasses import dataclass

from dfs_optimizer.models import Platform


@dataclass(frozen=True, slots=True)
class SingleGameRules:
    platform: Platform
    multiplier_slot: str
    salary_cap: int
    flex_slots: int = 5
    multiplier: float = 1.5
    minimum_teams: int = 2

    @property
    def lineup_size(self) -> int:
        return 1 + self.flex_slots


SINGLE_GAME_RULES = {
    Platform.DRAFTKINGS: SingleGameRules(Platform.DRAFTKINGS, "CPT", 50_000),
    Platform.FANDUEL: SingleGameRules(Platform.FANDUEL, "MVP", 60_000),
}


def single_game_rules_for(platform: Platform) -> SingleGameRules:
    return SINGLE_GAME_RULES[platform]
