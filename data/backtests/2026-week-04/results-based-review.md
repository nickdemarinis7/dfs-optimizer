# 2026 Week 4 results-based portfolio review

This review uses the entered rosters and final contest standings. It does not
have the original projection snapshots, so it evaluates portfolio construction
and realized outcomes rather than claiming to measure pre-lock projection
accuracy.

`Top %` is `rank / field size`; lower is better. Duplication is the number of
field entries with the same roster. FanDuel Showdown duplication is based on
the same six-player combination because its export does not identify the MVP
slot in each field lineup.

## Results

| Contest | Lineup | Score | Rank | Field | Top % | Duplication |
|---|---:|---:|---:|---:|---:|---:|
| FanDuel Classic | 1 | 97.52 | 66,097 | 102,384 | 64.6% | 1 |
| FanDuel Classic | 2 | 90.66 | 77,305 | 102,384 | 75.5% | 1 |
| FanDuel Classic | 3 | 74.36 | 95,545 | 102,384 | 93.3% | 1 |
| FanDuel Showdown | 1 | 115.49 | 8,922 | 26,117 | 34.2% | 3* |
| FanDuel Showdown | 2 | 78.33 | 24,367 | 26,117 | 93.3% | 41* |
| FanDuel Showdown | 3 | 94.99 | 18,280 | 26,117 | 70.0% | 1* |
| DraftKings Classic | 1 | 124.06 | 63,130 | 161,764 | 39.0% | 1 |
| DraftKings Classic | 2 | 108.58 | 102,240 | 161,764 | 63.2% | 1 |
| DraftKings Classic | 3 | 106.46 | 107,496 | 161,764 | 66.5% | 1 |
| DraftKings Showdown | 1 | 99.79 | 57,129 | 78,431 | 72.8% | 33 |
| DraftKings Showdown | 2 | 97.09 | 60,015 | 78,431 | 76.5% | 1 |
| DraftKings Showdown | 3 | 84.03 | 74,193 | 78,431 | 94.6% | 49 |

`*` FanDuel Showdown combination duplication, not confirmed MVP-specific duplication.

No lineup finished in the top third of its field. The best result was FanDuel
Showdown lineup 1 at top 34.2%, followed by DraftKings Classic lineup 1 at top
39.0%.

## What worked

- All six Classic lineups were unique in their respective fields. The
  uniqueness rules produced differentiated rosters without obvious duplication.
- FanDuel Showdown lineup 1 correctly used Bryce Young at MVP. His multiplied
  contribution was 36.69 points, and Chuba Hubbard added 28.40.
- DraftKings Classic lineup 1 captured Puka Nacua's 30.70 points along with
  useful scores from George Kittle, Michael Wilson, James Cook III, and Derrick
  Henry.
- The Classic lineups generally preserved QB-stack and bring-back structure.
  The problem was the realized quality of several stack partners, not the
  absence of correlation rules.

## What hurt

### Repeated low-floor selections

- Kenyon Sadiq scored 0 and appeared in two lineups on each site: four of the
  six Classic entries in total.
- The Raiders defense scored 1 and appeared twice on each Classic site.
- Dalton Kincaid scored 1.20 on FanDuel, Dalton Schultz scored 1.90 FanDuel / 
  2.90 DraftKings, and Courtland Sutton scored 1.40 DraftKings points.
- Jalen Coker and Casey Washington each scored 0 in single-game lineups.

The per-site two-of-three exposure limit worked mechanically, but it still
allowed speculative players to become major cross-platform positions.

### Insufficient ceiling coverage

- CeeDee Lamb led the Classic slates with 35.80 FanDuel and 44.30 DraftKings
  points but appeared in none of the six Classic lineups.
- Nico Collins scored 30.30 FanDuel / 33.80 DraftKings and was also absent.
- Tetairoa McMillan dominated the single-game slate with 61.80 FanDuel / 48.20
  DraftKings base points and appeared in none of the six Showdown lineups.
- Jahmyr Gibbs occupied two of three multiplier slots on each site, limiting
  the portfolio's paths to a different slate-winning outcome.

These are hindsight results, so they do not prove those players were bad
pregame omissions. They do show that the three-lineup portfolios did not cover
enough distinct ceiling scenarios.

### Showdown duplication

Two DraftKings Showdown lineups were duplicated 33 and 49 times. FanDuel's
second six-player combination appeared 41 times. Even if those builds had
scored better, ties would have reduced tournament upside.

## Changes justified by this sample

1. **Add a speculative-player exposure tier.** Keep the general 67% cap, but
   cap low-role, low-volume, or weakly established players at one of three
   lineups unless explicitly locked.
2. **Track exposure across platforms.** Warn when the same fragile player is
   used heavily in both the DraftKings and FanDuel portfolios.
3. **Require evidence of role.** Add recent snaps, routes, targets, carries, or
   depth-chart status to the eligibility gate so a projection alone cannot
   make a near-zero-role player a repeated value play.
4. **Diversify multiplier scenarios.** Default three-max Showdown portfolios
   to three distinct MVP/Captain players when enough viable ceiling candidates
   exist, with an override for unusually concentrated slates.
5. **Penalize duplicated Showdown constructions.** Use projected ownership and
   lineup ownership product/geometric mean as an objective penalty, especially
   for lineups with a chalk multiplier and chalk five-player core.
6. **Broaden ceiling-lineup coverage.** The ceiling build should reward a
   distinct game script and primary stack rather than simply increasing the
   ceiling weight on a core shared with the balanced builds.

## Data limitations

- Original pre-lock projection snapshots are unavailable.
- The archived DraftKings Showdown salary CSV is for a different game, so that
  slate cannot be replayed exactly.
- Entry fees and payout data are absent, so ROI cannot be calculated.
- This is one week and should guide safeguards, not wholesale model fitting.
