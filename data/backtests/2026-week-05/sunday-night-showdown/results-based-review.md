# NFL results review — 2026 Week 5 Sunday night Showdown

## Scope

All three FanDuel and all three DraftKings entered lineups matched the final
standings. Salary files, submitted rosters, player outcomes, ownership, ranks,
and exact-lineup duplication were available. The generation archive was not
saved, so the original projections and optimizer settings cannot be audited.

## Results

### FanDuel

| Lineup | Score | Rank | Finish | Exact duplicates | MVP |
| ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 96.05 | 5,762 of 25,251 | top 22.82% | 21 | Derrick Henry |
| 2 | 83.00 | 16,533 of 25,251 | top 65.47% | 34 | Bijan Robinson |
| 3 | 97.85 | 4,273 of 25,251 | top 16.92% | 13 | Kyle Pitts Sr. |

The winning score was 116.29. The top-10% threshold was 100.54 and the top-5%
threshold was 103.39.

### DraftKings

| Lineup | Score | Rank | Finish | Exact duplicates | Captain |
| ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 91.30 | 35,438 of 78,431 | top 45.18% | 26 | Bijan Robinson |
| 2 | 98.60 | 15,552 of 78,431 | top 19.83% | 21 | Derrick Henry |
| 3 | 87.50 | 45,662 of 78,431 | top 58.22% | 1 | Kyle Pitts Sr. |

The winning score was 123.06. The top-10% threshold was 102.40 and the top-5%
threshold was 105.74.

## Main finding: the replacement quarterback was missed

Lamar Jackson was marked OUT in both salary files. Tyler Huntley was the active
replacement and scored 24.04 points, the highest unmultiplied score on FanDuel
and essentially tied with Derrick Henry for the highest DraftKings score.
Huntley was not a hidden hindsight play: he was selected by 55.11% of the
FanDuel field and 39.24% of the DraftKings field. None of the six entered
lineups included him.

The winning DraftKings lineup used Huntley at Captain. The winning FanDuel
lineup used Henry at MVP with Huntley in FLEX. Omitting Huntley from every
lineup removed the most important game script from the portfolio.

The code review found a related pre-lock risk. A depth-chart QB2 could still be
classified as a backup when the QB1 was unavailable, and relief-appearance
history could leave the replacement's projection far below a starter-level
expectation. Both paths have now been corrected: an unavailable QB1 no longer
causes the active QB2 to be excluded, and the highest active replacement gets a
conservative 70% transfer of the unavailable starter's projection distribution.

## Portfolio construction

- FanDuel used Henry, Bijan, and Michael Penix Jr. in all three lineups.
  DraftKings used those three plus Kyle Pitts in all three. The portfolio
  diversified multiplier roles but remained too concentrated in its FLEX core.
- The multiplier choices themselves were reasonable. Henry produced each
  site's best entered multiplier result, and the contrarian Pitts MVP lineup
  was the best FanDuel finish.
- Cheap-player selection was mixed. Justice Hill and Devontez Walker provided
  useful salary relief. Austin Hooper scored zero, and Brian Robinson Jr.
  scored 1.6. Current maximum-once and fragile-role controls should keep those
  types of uncertain values from becoming repeated portfolio dependencies.
- Exact duplication was moderate for five lineups and only one DraftKings
  lineup was unique. This mattered less than missing Huntley, but projected
  ownership and duplication should be reviewed once a full run archive exists.

## Decisions for the next slate

1. Promote the active replacement quarterback when QB1 is unavailable instead
   of treating relief-game averages as the expected starting role.
2. Never exclude a depth-chart QB2 solely because an unavailable QB1 remains
   listed above him.
3. Retain diversified Captain/MVP choices; that portion of the portfolio acted
   as intended.
4. Retain the default 67% player-exposure limit for a three-lineup portfolio so
   no non-locked player becomes an automatic three-of-three core.
5. Save tonight's full run ZIP. It is required to verify projection accuracy,
   ownership inputs, and whether any fallback relaxed the requested exposure.

## Additional pre-lock hardening

- The pre-lock screen now stops labeling an active QB2 as a backup when QB1 is
  unavailable.
- If a strict Showdown portfolio is infeasible, the app first reduces lineup
  uniqueness while preserving player exposure. It may then relax Max once, but
  it no longer silently raises player exposure to 100%. A three-of-three core
  now requires the user to choose a higher exposure setting explicitly.
