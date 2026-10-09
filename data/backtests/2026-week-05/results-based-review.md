# 2026 Week 5 results review

This review uses the final contest standings as the source of truth. The saved
lineup exports contain three entries per site, while the standings contain four
submitted `nick_demarinis` entries per site. Because changes were made near
lock, conclusions about actual submissions come from the standings—not from the
older exports.

## Executive summary

- The best DraftKings lineup finished **146th of 88,235** (top **0.17%**) with
  **132.81** points, only **3.78** behind the winning score of 136.59.
- That lineup was duplicated 13 times exactly. Fifteen entries shared its final
  score.
- The lineup was reportedly second with under four minutes remaining. The final
  export does not contain rank-over-time data, so that live rank cannot be
  independently reconstructed.
- The other three DraftKings entries finished 64,785th, 72,202nd, and 72,487th.
  This was a high-variance portfolio: one elite outcome and three misses.
- The best FanDuel entry finished 14,052nd of 37,698 (top 37.28%). The remaining
  entries finished 23,580th, 29,744th, and 31,401st.

## Actual DraftKings entries

| Rank | Score | Exact duplicates | Captain | FLEX |
| ---: | ---: | ---: | --- | --- |
| 146 | 132.81 | 13 | Bucky Irving | George Pickens; Jalon Daniels; Emeka Egbuka; Chris Godwin Jr.; Ryan Flournoy |
| 64,785 | 59.52 | 137 | Dak Prescott | CeeDee Lamb; Jalon Daniels; Brandon Aubrey; Cade Otton; Kenny Gainwell |
| 72,202 | 53.99 | 213 | CeeDee Lamb | Javonte Williams; Dak Prescott; Kenny Gainwell; Ryan Flournoy; Ted Hurst III |
| 72,487 | 53.94 | 5 | Kenny Gainwell | CeeDee Lamb; Javonte Williams; Dak Prescott; Brandon Aubrey; Cade Otton |

The near-winner succeeded through a low-owned Captain and a correlated group of
ceiling outcomes. Bucky Irving was 4.98% Captain-owned. George Pickens scored
31.0 FLEX points, Emeka Egbuka 17.2, Jalon Daniels 13.86, Ryan Flournoy 12.0,
and Chris Godwin Jr. 7.0.

The winning lineup replaced Jalon Daniels plus Chris Godwin Jr. (20.86 combined)
with Dak Prescott plus Chase McLaughlin (24.64 combined). That two-player swap
accounts exactly for the 3.78-point gap.

## Actual FanDuel entries

FanDuel's export lists the MVP first even though the lineup text shows the
player's football position. The review parser now preserves this role.

| Rank | Score | Exact duplicates | MVP | FLEX |
| ---: | ---: | ---: | --- | --- |
| 14,052 | 79.36 | 1 | Dak Prescott | CeeDee Lamb; Bucky Irving; Javonte Williams; Kenny Gainwell; Joe Milton III |
| 23,580 | 63.82 | 75 | Dak Prescott | Luke Schoonmaker; Chase McLaughlin; Jalon Daniels; Javonte Williams; CeeDee Lamb |
| 29,744 | 55.49 | 18 | CeeDee Lamb | Dak Prescott; Javonte Williams; Kenny Gainwell; Chase McLaughlin; Ryan Flournoy |
| 31,401 | 52.64 | 87 | Javonte Williams | CeeDee Lamb; Dak Prescott; Kenny Gainwell; Brandon Aubrey; Cade Otton |

## Projection findings

The archived DraftKings snapshot projected the four submitted entries at 64.73,
97.59, 109.07, and 106.13 points respectively. Their actual scores were 132.81,
59.52, 53.99, and 53.94. The lowest-median lineup produced the tournament result,
which reinforces the value of reserving one lineup for a distinct ceiling/game
script rather than producing three small variations of the median build.

The archived run used a hard minimum multiplied Captain ceiling of 20 points.
Bucky Irving's value was 19.88, excluding him by roughly 0.12 despite his strong
relative projection. The app now uses 18 points so near-threshold candidates are
not removed categorically. This is a narrow rule correction, not a wholesale
model recalibration from one outcome.

## Product gaps closed

1. **Actual entries versus generated runs:** the Backtest screen now extracts all
   entries matching the supplied username and treats them as authoritative. It
   warns when the submitted count or lineups differ from the saved run.
2. **FanDuel MVP identity:** FanDuel single-game matching now preserves the first
   lineup player as MVP. Previously, identical six-player sets with different
   MVPs could be conflated.
3. **Captain cutoff:** the multiplied-ceiling gate was lowered from 20 to 18 to
   avoid false precision at a hard boundary.
4. **Duplication:** reviews report exact lineup duplication, including Captain or
   MVP role, rather than only counting equal final scores.

## Remaining gaps

- A final platform entry-template download or post-lock snapshot is still needed
  to prove exactly what was submitted before results exist. The standings solve
  this after the contest, not before it.
- The final CSV cannot reconstruct live rank changes. Capturing screenshots or a
  contest-history timeline is required to validate late-game movement.
- One exceptional tournament result is evidence that the construction can reach
  the top of a large field, but it is not enough to establish predictive edge.
  Continue collecting salary files, immutable run packages, actual submissions,
  ownership, final standings, and payouts across many slates.
- Reliable projected ownership was absent from the archived projection snapshot,
  so pre-lock duplication and leverage could not be modeled directly.
