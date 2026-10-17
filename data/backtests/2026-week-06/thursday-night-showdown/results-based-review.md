# NFL results review — 2026 Week 6 Thursday night Showdown

## Data quality

Both final run archives are complete and contain the salary file, projections,
settings, and three generated lineups. The two earlier FanDuel archives are
also retained, and final standings are available for both platforms. Four
entries were submitted on each platform. Every FanDuel entry matches a saved
app archive. Two DraftKings entries match the final saved archive; the other
two cannot be tied to a saved app run and are shown only as unverified contest
context, not as optimizer validation.

## Submitted results

### FanDuel

| Entry | Run | Score | Rank | Finish | Exact copies | MVP |
| ---: | --- | ---: | ---: | ---: | ---: | --- |
| 1 | Verified prior app run | 59.40 | 21,076 of 37,365 | top 56.41% | 381 | Jaxon Smith-Njigba |
| 2 | Final | 69.41 | 6,860 of 37,365 | **top 18.36%** | 53 | Sam Darnold |
| 3 | Final | 64.50 | 13,810 of 37,365 | top 36.96% | 262 | Jaxon Smith-Njigba |
| 4 | Final | 54.04 | 27,390 of 37,365 | top 73.30% | 11 | Bo Nix |

The winning score was 89.02. The top-20% threshold was 69.12, so the best
lineup cleared it by 0.29 points. The top-10% threshold was 72.53.

### DraftKings

| Entry | Run | Score | Rank | Finish | Exact copies | Captain |
| ---: | --- | ---: | ---: | ---: | ---: | --- |
| 1 | Unverified—excluded from validation | 68.42 | 51,744 of 84,179 | top 61.47% | 45 | Emanuel Wilson |
| 2 | Unverified—excluded from validation | 45.52 | 79,980 of 84,179 | top 95.01% | 15 | Bo Nix |
| 3 | Final | 79.82 | 23,005 of 84,179 | **top 27.33%** | 31 | RJ Harvey |
| 4 | Final | 76.00 | 32,532 of 84,179 | top 38.65% | 99 | Jaxon Smith-Njigba |

The unentered final Bo Nix Captain lineup scored 52.72 and would have ranked
74,505. The winning score was 106.62. The top-20% threshold was 82.02 and the
top-10% threshold was 86.20.

## Projection calibration

| Platform | Players | MAE | RMSE | Bias | Correlation | Floor-ceiling coverage | Above ceiling |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| FanDuel | 23 | 3.25 | 4.05 | -0.05 | 0.680 | 78.3% | 8.7% |
| DraftKings | 22 | 3.81 | 4.88 | -0.36 | 0.655 | 68.2% | 18.2% |

Aggregate bias was nearly zero, so the slate does not support globally raising
or lowering projections. Player ordering was considerably weaker than the
previous Monday slate. The largest common misses were Bo Nix (overprojected),
Jaxon Smith-Njigba (underprojected), RJ Harvey (underprojected), Seattle's
defense (overprojected), Emanuel Wilson (overprojected), Cooper Kupp
(underprojected), and Rashid Shaheed (underprojected).

The range model was reasonably calibrated on FanDuel. DraftKings had four of
22 players exceed their ceiling, which remains higher than desired but is not
enough evidence for another global range expansion.

## Construction findings

- The final FanDuel run used a user-selected 100% exposure cap after the 67%
  run proved difficult. Darnold, Nix, and Jason Myers therefore appeared in
  every lineup. Nix's 4.48 points hurt all three entries. This is the clearest
  avoidable portfolio-level risk from the slate.
- The final DraftKings portfolio retained the preferred 67% cap. Its best
  lineup was the RJ Harvey Captain build, while the unentered Bo Nix Captain
  build was its weakest. Exposure diversification reduced the damage.
- The winning DraftKings lineup used Smith-Njigba at Captain with Darnold,
  Dobbins, Harvey, Shaheed, and Kupp. The winning FanDuel construction used
  Smith-Njigba at MVP with Darnold, Harvey, Shaheed, Denver's defense, and
  Myers. The optimizer identified Smith-Njigba multiplier and Harvey Captain
  paths, but did not combine enough of the mid-salary receiving and rushing
  upside around them.
- Duplication was especially poor for the FanDuel Smith-Njigba MVP lineup at
  262 exact copies. The earlier FanDuel lineup containing Nate Adkins was
  duplicated 381 times and still carried a near-zero-role player. The final
  exclusions improved safety but did not solve duplication without projected
  ownership data.
- The model reduced Cooper Kupp by 25% solely because the external feed called
  him WR3. That classification is not reliable evidence of a bench role in the
  NFL, where a third receiver can be a starting slot player. The penalty made
  an already-low projection even less competitive.

## Changes made

1. WR3 is no longer automatically projection-penalized. WR4 and deeper still
   receive the role penalty; WR3 remains eligible for the conservative Max once
   safeguard.
2. A Showdown RB, WR, or TE with a projection below 1.5 points, a near-zero
   floor and 25th percentile, and at least 50% bust probability is now suggested
   for exclusion even when the live depth-chart feed has no match. This would
   have automatically caught both Michael Bandy and Nate Adkins profiles.
3. Run archives now correctly record the enforced one-fragile-player maximum
   for Showdown instead of serializing it as null.
4. The 67% three-lineup exposure default remains unchanged. This slate
   reinforces its value; raising it to 100% should remain a deliberate last
   resort rather than a recommended setting.

## Next evidence target

Projected ownership is still the most important missing pre-lock input. Actual
duplication shows that a sound median lineup can be too common to have strong
tournament value. Until an ownership source is connected, duplication should
be monitored rather than addressed with a speculative hard rule derived from a
single slate.
