from __future__ import annotations

import unittest

from dfs_optimizer.models import Platform, Position, Sport
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

    def test_draftkings_college_rules_include_super_flex(self) -> None:
        rules = classic_rules_for(Platform.DRAFTKINGS, Sport.CFB)

        self.assertEqual(rules.lineup_size, 8)
        self.assertEqual(rules.salary_cap, 50_000)
        self.assertEqual(rules.slots[-1].name, "S-FLEX")
        self.assertTrue(rules.slots[-1].accepts(Position.QB))

    def test_fanduel_college_rules_treat_tight_ends_as_receivers(self) -> None:
        rules = classic_rules_for(Platform.FANDUEL, Sport.CFB)

        self.assertEqual(rules.lineup_size, 7)
        self.assertEqual(rules.salary_cap, 60_000)
        self.assertTrue(rules.slots[3].accepts(Position.TE))


if __name__ == "__main__":
    unittest.main()
