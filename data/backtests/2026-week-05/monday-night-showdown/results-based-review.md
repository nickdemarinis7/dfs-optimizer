# NFL results review — 2026 Week 5 Monday night Showdown

## Data quality

Both run archives are complete and contain the exact salary file, projections,
settings, and three generated lineups. All three lineups from each archive
matched the corresponding final standings exactly. This is the first review in
this sequence where projection accuracy and lineup construction can both be
measured from the final saved run.

The archives were placed in `entered-lineups/` rather than `run-archives/`, but
their contents are valid and no review data is missing.

## Results

### FanDuel

| Lineup | Projection | Actual | Rank | Finish | Exact copies | MVP |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 95.91 | 124.98 | 14,811 of 37,698 | top 39.29% | 79 | Matthew Stafford |
| 2 | 92.36 | 119.30 | 21,150 of 37,698 | top 56.10% | 3 | Kyren Williams |
| 3 | 93.88 | 138.52 | 1,840 of 37,698 | **top 4.88%** | 15 | Tyler Higbee |

The winning score was 146.12. The top-5% threshold was 138.47, so lineup 3
cleared it by 0.05 points.

### DraftKings

| Lineup | Projection | Actual | Rank | Finish | Exact copies | Captain |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 102.56 | 143.17 | 12,897 of 88,235 | top 14.62% | 54 | Puka Nacua |
| 2 | 91.41 | 115.50 | 67,688 of 88,235 | top 76.71% | 9 | Kyren Williams |
| 3 | 102.97 | 141.68 | 15,449 of 88,235 | top 17.51% | 55 | Matthew Stafford |

The winning score was 166.57. The top-10% threshold was 146.37 and the top-20%
threshold was 140.28.

## Projection calibration

| Platform | Players | MAE | RMSE | Bias | Correlation | Floor–ceiling coverage | Above ceiling |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| FanDuel | 25 | 4.23 | 5.60 | -1.85 | 0.929 | 52.0% | 28.0% |
| DraftKings | 23 | 4.63 | 6.29 | -2.61 | 0.937 | 56.5% | 30.4% |

The negative bias means the model underestimated scoring in this game. Player
ranking was nevertheless strong: correlations above 0.92 show that the model
generally ordered players correctly. The larger weakness was uncertainty
calibration. Roughly 30% of players beat their modeled ceiling, far more than a
well-calibrated upper range should permit.

The largest underestimates were the game's stars: Puka Nacua, Josh Allen,
James Cook III, Matthew Stafford, and Blake Corum. This explains why all six
lineups materially outscored their median projections. One slate is not enough
to globally increase every median, but it is evidence that empirical ceilings
need continued multi-slate calibration.

## Construction findings

- The 67% exposure rule worked. No player appeared in all three lineups on
  either platform, and the archives confirm that constraints were not relaxed.
- FanDuel lineup 3 combined Allen, Nacua, Stafford, Cook, Higbee, and one punt.
  Five strong outcomes overcame Konata Mumpfield's zero and produced a top-5%
  result.
- DraftKings lineup 1 correctly used Nacua at Captain and included Stafford.
  It missed the top 10% by 3.20 points. The winning lineup also used Nacua at
  Captain, but paired the major stars with Blake Corum and Ty Johnson.
- DraftKings lineup 2 failed because its Kyren Captain construction included
  Colby Parkinson (1.3) and Tutu Atwell (1.4). The Max once controls contained
  those thin-role plays to a single lineup.
- Duplication remained meaningful: the strongest DraftKings builds had 54 and
  55 exact copies. Projected ownership was absent, so the optimizer could not
  deliberately trade projection against duplication before lock.

## Adjustments and next evidence target

1. Keep the current exposure, uniqueness, and Max once defaults. They behaved
   correctly and prevented the concentrated-core problem seen Sunday night.
2. Do not remove contrarian multiplier options. Higbee MVP created the top-5%
   FanDuel result, while Nacua Captain was the correct DraftKings archetype.
3. Continue gathering complete archives before changing global medians or
   ceiling multipliers. The range miss is real, but one high-scoring game is
   not enough to determine the right calibration factor.
4. Add projected ownership when available. Actual duplication shows that
   projection-only portfolio scoring still produces common constructions.
5. Fix live-context coverage accounting for Showdown archives. The numerator
   previously included every salary-pool context while the denominator included
   only projected players, inflating recorded coverage to 192%–204%. Coverage
   now compares the same projected-player set on both sides.

## Zero-floor punt adjustment

Konata Mumpfield was not merely a low-scoring outcome. His saved projection had
a zero floor, zero 25th percentile, 71.9% DraftKings bust probability, 81.3%
FanDuel bust probability, and a WR3 depth-chart designation. The existing Max
once rule contained him to one lineup but still allowed the lineup-level zero.

Showdown now suggests excluding a skill-position punt by default when all of
the following are true: projection below five points, floor and 25th percentile
at or below 0.5, bust probability of at least 70%, and depth order of three or
worse. The user can override the suggestion. This preserves useful salary
relief with demonstrated opportunity—such as Ty Johnson—while removing the
most extreme no-role profiles.

The optimizer also now limits each Showdown lineup to one remaining fragile
RB, WR, or TE and applies a small objective penalty for modeled bust
probability. This controls cumulative zero risk without banning a single punt
that unlocks a strong ceiling construction.
