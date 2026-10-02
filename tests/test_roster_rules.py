from __future__ import annotations

import unittest

from dfs_optimizer.models import Platform, Position
from dfs_optimizer.rules import classic_rules_for


class ClassicRosterRuleTests(unittest.TestCase):
    def test_draftkings_rules(self) -> None:
        rules = classic_rules_for(Platform.DRAFTKINGS)
        self.assertEqual(rules.salary_cap, 50_000)
        self.assertEqual(rules.lineup_size, 9)
        self.assertEqual([slot.name for slot in rules.slots], [
            "QB", "RB1", "RB2", "WR1", "WR2", "WR3", "TE", "FLEX", "DST"
        ])

    def test_fanduel_rules(self) -> None:
        rules = classic_rules_for(Platform.FANDUEL)
        self.assertEqual(rules.salary_cap, 60_000)
        self.assertEqual(rules.lineup_size, 9)

    def test_flex_accepts_only_skill_positions(self) -> None:
        flex = classic_rules_for(Platform.DRAFTKINGS).slots[7]
        self.assertTrue(flex.accepts(Position.RB))
        self.assertTrue(flex.accepts(Position.WR))
        self.assertTrue(flex.accepts(Position.TE))
        self.assertFalse(flex.accepts(Position.QB))
        self.assertFalse(flex.accepts(Position.DST))


if __name__ == "__main__":
    unittest.main()

