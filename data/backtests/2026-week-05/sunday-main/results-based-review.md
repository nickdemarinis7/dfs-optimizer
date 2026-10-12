# NFL results review — 2026 Week 5 Sunday main slate

## Scope and data quality

All six entered lineups match the final contest standings. The review includes
the original salary files, entered rosters, final player scores, field
ownership, exact-lineup duplication, and contest ranks.

The pre-lock run archive and projection snapshot were not saved. Consequently,
this review can evaluate outcomes and construction, but it cannot calculate
projection error, compare projected ownership with actual ownership, or prove
which optimizer settings produced these lineups.

## Executive summary

- The best FanDuel lineup scored **182.42**, finished **2,386th of 99,740**
  (top **2.39%**), and was unique.
- The best DraftKings lineup scored **159.18**, finished **23,758th of
  161,557** (top **14.71%**), and was unique.
- The FanDuel portfolio produced one strong tournament result, one top-20%
  result, and one below-median result. The DraftKings portfolio did not reach
  the top 10%.
- Double TE was not the central problem. The LaPorta–McBride lineup was the
  best DraftKings lineup, and the same pairing scored 34.4 FanDuel points.
- Thin current roles were a real problem. Michael Mayer scored **1.2**
  DraftKings points and appeared in two of three DraftKings lineups.
- Lineup correlation and portfolio diversity were generally sound. The larger
  opportunity is improving current-role and weak-value selection.

## FanDuel results

| Lineup | Score | Rank | Finish | Duplicates | Salary |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 157.48 | 16,369 | top 16.41% | 1 | $59,800 |
| 2 | 123.86 | 61,384 | top 61.54% | 1 | $59,900 |
| 3 | 182.42 | 2,386 | top 2.39% | 1 | $59,800 |

Useful field reference points were 190.36 for the top 1%, 174.36 for the top
5%, 165.26 for the top 10%, and 131.84 at approximately the median. The winning
score was 232.98.

Lineup 3 was the clear success. Jared Goff (28.94), Jahmyr Gibbs (38.2), Malik
Nabers (26.6), Sam LaPorta (17.3), Jaylen Warren (36.8), and Rhamondre
Stevenson (16.0) supplied the ceiling. Its Goff–Gibbs–LaPorta stack was a strong
correlated construction. Michael Wilson (5.28) and Wan'Dale Robinson (8.3)
prevented a still higher finish.

Lineup 2's LaPorta–McBride combination scored 34.4 points. Its failure came
elsewhere: Chris Olave scored 6.6, Michael Wilson 5.28, and the Raiders defense
minus 1.0. This is evidence against blaming or categorically banning double TE.

## DraftKings results

| Lineup | Score | Rank | Finish | Duplicates | Salary |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 129.46 | 86,443 | top 53.51% | 1 | $50,000 |
| 2 | 159.18 | 23,758 | top 14.71% | 1 | $50,000 |
| 3 | 144.90 | 49,786 | top 30.82% | 2 | $50,000 |

Useful field reference points were 193.66 for the top 1%, 175.58 for the top
5%, 165.56 for the top 10%, and 131.82 at approximately the median. The winning
score was 250.06.

Lineup 2 was the best build. Jaylen Warren (39.8), Malik Nabers (32.1), Jacoby
Brissett (26.28), Sam LaPorta (19.8), and Trey McBride (21.6) all worked. RJ
Harvey (0.7) and the Raiders defense (minus 1.0) combined for minus 0.3, while
Olave added only 8.6. The lineup finished 6.38 points below the top-10%
threshold. Its two tight ends combined for 41.4 points and were an advantage,
not a defect.

Michael Mayer scored 1.2 points in lineups 1 and 3. Tucker Kraft and Mayer
combined for only 12.8 points in lineup 1; LaPorta and Mayer combined for 21.0
in lineup 3. The distinction is role quality, not the number of tight ends.

## Portfolio construction

- Pairwise overlap was modest: FanDuel lineups shared two to four players and
  DraftKings lineups shared two to four players. No player appeared in all
  three lineups on either site.
- Every entered lineup used a quarterback pass catcher, and several included a
  reasonable opponent bring-back. The best FanDuel lineup also captured the
  high-scoring Detroit core.
- Five of six lineups were unique in their contests. DraftKings lineup 3 was
  duplicated only once. Duplication was therefore not a meaningful failure.
- All DraftKings lineups used the full salary cap. FanDuel left only $100–$200.
  There is no indication that excessive unused salary caused the misses.
- The DraftKings builds were very contrarian outside of Brissett. Several
  selected players were below 1% owned. Low ownership created uniqueness, but
  stacking multiple thin outcomes increased failure risk without enough
  evidence that each play had a current role capable of producing a ceiling.

## What the hindsight lineup says—and does not say

The highest possible salary-valid lineup from the final outcomes scored 267.56
on FanDuel and 284.76 on DraftKings. Both used Drake Maye, Gibbs, Warren, Malik
Nabers, DeMario Douglas, Isaiah Likely, and a high-scoring defense; the remaining
receivers differed by site.

This is useful for identifying where slate-winning points existed, but it is
not a projection and was unknowable before lock. It should not be used to tune
the model toward individual Week 5 winners.

## Decisions and next calibration targets

1. **Keep double TE available.** Monitor its frequency and results, but do not
   add a hard cap. This slate contains direct evidence that the construction
   can be the better lineup when both roles are strong.
2. **Keep the current-role safeguards.** The newer depth-chart, snap-trend, and
   fragile-value logic directly targets the Michael Mayer failure mode. A TE2+
   can remain eligible when news supports a larger role, but should not become
   a two-lineup core because of stale starter-period production.
3. **Require stronger evidence for sub-1% value cores.** Contrarian players are
   useful, but low ownership is not itself upside. Current snaps, depth order,
   opportunity trend, and ceiling should support each thin play.
4. **Do not overfit to one slate.** The optimizer found a top-2.39% lineup and
   several excellent individual plays. The evidence supports narrow role-risk
   improvements rather than a broad rewrite of stacking or roster rules.
5. **Preserve the next run archive.** Save the final generation ZIP and the
   post-lock submission snapshot. That will allow projection MAE, ownership
   calibration, optimizer-versus-projection diagnosis, and early-versus-late
   run comparisons on the next review.

## Implemented for Week 6

- NFL Classic lineups are now limited to at most two players classified as
  fragile values. This prevents a single lineup from depending on several
  uncertain roles without banning contrarian selections.
- NFL RB, WR, and TE projections below 10 points with a modeled bust
  probability of at least 45% are now suggested as maximum-once plays in a
  portfolio. Existing depth-chart and near-zero-floor signals still apply.
- Productive double-TE combinations remain eligible. The restrictions apply to
  individual role risk, not to the number of tight ends in a lineup.
