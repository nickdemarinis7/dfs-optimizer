# Retrospective portfolio study

## Method

The Showdown portion uses four contest/platform pairs that contain both an original
pre-lock run archive and complete contest standings. The archived projections
remain fixed. Only the current Showdown portfolio-construction logic is used to
regenerate three lineups. Both portfolios are then scored from the final player
results and ranked hypothetically against the real contest field.

This isolates optimizer changes better than rebuilding historical projections
with information learned after the contest. It is still retrospective and the
sample is small, so it is diagnostic evidence rather than an unbiased estimate
of future ROI.

| Contest | Platform | Original best | Current best | Original average score | Current average score |
| --- | --- | ---: | ---: | ---: | ---: |
| Week 6 Thursday Showdown | DraftKings | Top 27.26% | Top 14.66% | 69.51 | 76.17 |
| Week 6 Thursday Showdown | FanDuel | Top 18.36% | Top 35.59% | 62.65 | 61.98 |
| Week 5 Monday Showdown | DraftKings | Top 14.62% | Top 11.13% | 133.45 | 137.71 |
| Week 5 Monday Showdown | FanDuel | Top 4.89% | Top 7.13% | 127.60 | 128.73 |

## Aggregate findings

- Mean lineup finish improved from the top 41.00% of the field to the top
  34.08%.
- Median lineup finish improved from approximately top 37.76% to top 30.00%.
- Five of twelve regenerated lineups finished in the top 20%, compared with
  four of twelve original lineups.
- The best lineup improved in two of four platform/slate comparisons.
- Average portfolio score improved in three of four comparisons.
- The current rules removed Konata Mumpfield from both Week 5 portfolios. His
  zero-target outcome no longer damaged either regenerated portfolio.

## What the results suggest

The newer construction rules appear to improve portfolio depth and reduce the
worst fragile-role failures. That is visible in the stronger mean and median
field finishes. They have not yet demonstrated a consistent improvement in the
single best tournament lineup, which is the most important outcome for a
three-entry GPP portfolio.

The Week 6 FanDuel regression is especially useful. The regenerated portfolio
used more defense-oriented construction and missed Rashid Shaheed, who appeared
in the winning lineup. Because the archived projections were held constant,
this points to a remaining portfolio-selection or upside-allocation question,
not hindsight contamination from rebuilt projections.

## Next validation step

Repeat this fixed-projection comparison for every future archived run. Report
best finish, median finish, top-1%, top-10%, and top-20% hit rates by platform.
Do not promote another hard optimizer rule until the same effect appears across
multiple independent slates.

## Classic replay

The same fixed-projection method was applied to the available Week 6 Sunday
Classic archives. To keep the replay practical, the current 3-max selector
searched eight candidates per objective rather than the production default of
twenty. It exercises the current eligibility, exposure, stacking, bring-back,
ceiling, and portfolio-selection rules, but should be treated as a conservative
approximation of a full production run.

| Platform | Original best | Current best | Original average score | Current average score | Original average finish | Current average finish |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DraftKings | Top 70.01% | Top 70.01% | 103.11 | 104.37 | Top 79.88% | Top 80.07% |
| FanDuel | Top 57.18% | Top 58.02% | 93.35 | 100.51 | Top 78.92% | Top 69.39% |

Across the six Classic lineups, mean field finish improved from top 79.40% to
top 74.73%, and median finish improved from top 78.10% to top 73.56%. Average
portfolio score improved on both platforms, but neither platform produced a
better best lineup. The current rules therefore improved portfolio depth in
this slate without solving the more important problem: the archived player
projections did not identify enough of the slate's tournament-winning upside.

### Classic failure decomposition

The final scores make the projection limitation concrete. The winning scores
were 210.50 on DraftKings and 194.62 on FanDuel. Legal hindsight-optimal
lineups from the same salary pools scored 236.26 and 215.16, respectively, so
the salary files and roster rules contained ample upside.

The largest shared miss was Omar Cooper Jr.: projected for 0.18 DraftKings
points and 0.14 FanDuel points, he scored 25.3 and 22.3. Other materially
underprojected results included Tre Tucker, Germie Bernard, Kenneth Walker III,
Tyler Shough, and the Titans defense. Meanwhile, the optimizer concentrated on
players such as Derrick Henry, Rhamondre Stevenson, Puka Nacua, and Jaylen
Warren, all of whom missed their archived projections by double digits on at
least one platform.

The expensive-player misses include normal weekly variance and should not be
converted directly into hard avoidance rules. The actionable failure is that
the deterministic candidate-generation stage had no plausible route to an
emerging player projected near zero. Simulating outcomes only after candidates
have been generated cannot recover a player who never appears in those
candidates.

Priority improvements are therefore:

1. Generate part of the Classic candidate pool from role-aware ceiling
   scenarios, rather than selecting every candidate from deterministic mean and
   ceiling blends.
2. Audit near-zero projections against current depth chart, active status,
   recent routes/snaps/targets, and late player news before optimization.
3. Surface unexplained near-zero projections in preflight instead of silently
   treating them as reliable.
4. Track projection error separately from construction regret so normal star
   busts do not cause overfit lineup rules.

## Overall conclusion

The replays support keeping the recent risk and portfolio changes: average
field finish improved in both formats, and Showdown produced one additional
top-20% lineup. They do not support claiming that the optimizer is consistently
finding a better tournament winner. The next gains should come from projection
and ceiling calibration, late role/news inputs, and a growing out-of-sample
archive—not from adding more rigid lineup rules based on these six contests.
