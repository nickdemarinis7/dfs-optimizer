# NFL DFS Optimizer

An NFL daily-fantasy lineup optimizer for DraftKings and FanDuel Classic and
single-game contests.

The project currently imports and normalizes platform salary and projection
files and defines the NFL Classic roster constraints for both platforms.

## Local web app

Install the project, then launch the local interface:

```bash
python3 -m pip install -e .
dfs-app
```

The app opens in a browser and supports either a direct salary CSV upload or
an import folder. The default `samples/` folder acts as a simple inbox: place
new DraftKings or FanDuel CSVs there, refresh the app, and choose a detected
slate. Unrelated CSVs, such as contest history and results, are ignored.

The interface is a mobile-first three-step wizard. **Slate & projections** loads
the salary file and forecast, **Build lineups** handles player decisions and the
3-max strategy, and **Results** reviews one lineup at a time before download.
Primary buttons move forward only after each step is complete; technical details,
exposure, and audits stay in optional expanders. Slate, projection, and lineup
state carry across screens.

## Deploy to Streamlit Community Cloud

The repository is ready for Streamlit Community Cloud. Create an app from this
GitHub repository using:

- Repository: `nickdemarinis7/dfs-optimizer`
- Branch: `main`
- Main file: `src/dfs_optimizer/web_app.py`

`requirements.txt` installs the project and its dependencies. Historical NFL
data is downloaded into the deployment's ephemeral `data/cache/` directory as
needed, so a restarted deployment may need to download it again.

The Results screen includes a Sunday preflight gate before downloads unlock. It
independently checks lineup count, roster size, duplicate players, slate player
IDs, salary cap, minimum teams, positive projections, selected-player statuses,
and projection age. Because the app does not have a dependable live injury feed,
it also requires explicit confirmation that current injury/inactive news and the
intended platform, contest, and slate were reviewed.

The default projection source is the pregame historical forecast. Select the
target season and week, then build the forecast; the app can download the
target and previous season's nflverse inputs into `data/cache/`. For a target
week, the model filters player and team results to earlier weeks before adding
target-week matchup, market, game-script, and weather context. Target-week
results are never used as projection inputs.

The platform's fantasy-points average remains available as a clearly labeled
fallback. It is useful for exercising roster constraints and exports, but it
is not a forward-looking projection model.

## Getting salary CSVs

The dependable workflow is semi-automated: download each slate's official CSV
from DraftKings or FanDuel into the import folder and let the app detect and
parse it. The sites do not provide a stable, documented, unauthenticated salary
API. Automating a logged-in browser or private endpoint would be brittle and
could conflict with platform terms, so this project does not store credentials
or scrape those endpoints.

Contest-results CSVs should also be downloaded while they are available and
archived with the matching pre-lock salaries and projections for backtesting.

## Projection CSV format

Required columns are `name`, `team`, and `projected_points`. Optional columns
are `platform_id`, `floor`, `ceiling`, and `projected_ownership`. Ownership is
expressed as a percentage from 0 through 100. A platform ID is the strongest
match; otherwise, projections match salaries by normalized name and team.

## Inspect a salary file

From the project directory:

```bash
PYTHONPATH=src python -m dfs_optimizer.cli samples/DKSalaries.csv
```

Run the tests with:

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

Generate a Classic lineup once a full projection file is available:

```bash
PYTHONPATH=src python -m dfs_optimizer.cli samples/DKSalaries.csv \
  --projections path/to/full-projections.csv
```

For an end-to-end development smoke test, platform fantasy averages can be
used as a deliberately simple baseline:

```bash
PYTHONPATH=src python -m dfs_optimizer.cli samples/DKSalaries.csv --baseline
```

The baseline excludes players marked `IR`, `O`, or `OUT`. It is historical,
not forward-looking, and is not intended for lineup decisions.

## NFL scoring

Platform scoring is represented explicitly. DraftKings uses full PPR and
FanDuel uses half PPR. Both configurations include passing, rushing, receiving,
turnover, return, conversion, and yardage-bonus scoring. Scoring a stat line is
intended for realized or simulated outcomes; threshold bonuses should not be
applied directly to an average yardage projection.

The platform-neutral expected-stat format is demonstrated in
`examples/offensive-stat-projections.csv`. Expected stats are converted to the
correct platform points after joining them to a salary slate. Bonus fields are
probabilities from 0 through 1, so expected bonus value is calculated without
pretending the mean yardage is a realized game outcome.

Defense projections use expected sacks, turnovers, return events, and a full
probability distribution over the seven points-allowed scoring bands. See
`examples/defense-stat-projections.csv`. Using band probabilities avoids the
large error caused by placing an average opponent score into a single tier.

## Historical forecasts

The web app matches the games in an imported salary slate to the cached NFL
schedule and automatically selects the season and week. It displays the detected
period before projections are built. If the schedule is unavailable or the match
is ambiguous, the app requires an explicit week selection instead of silently
defaulting to Week 1.

`forecast_from_nflverse` ingests nflverse weekly player stats, weekly team
stats, and game results. It uses only regular-season games before the requested
target week and calculates recency-weighted expected stats and bonus/tier hit
probabilities. The default uses the last eight games with a four-game half-life.
Downloaded inputs belong in `data/cache/`, which is excluded from Git.

Download the current and prior seasons, forecast a target week, and optimize:

```bash
PYTHONPATH=src python -m dfs_optimizer.historical_cli samples/DKSalaries.csv \
  --season 2026 --week 4 --download \
  --lineups 20 --minimum-unique 2 --qb-stack 1 --bring-back
```

Tournament controls also include repeatable `--lock PLAYER_ID` and
`--exclude PLAYER_ID` options. Offenses facing a selected DST are prohibited by
default; use `--allow-dst-conflicts` to disable that constraint.

Use `--max-exposure 60` to limit unlocked players to 60% of the requested
portfolio and `--max-qb-exposure 67` to separately diversify quarterback
stacks. Exposure percentages are strict: in three lineups, 67% permits at most
two appearances. Locks override these caps. Add `--output lineups.csv` to
export roster columns using DraftKings `Name (ID)` cells or FanDuel slate
player IDs. Some contests require entry metadata from a platform-downloaded
template; the exporter does not invent that metadata.

For DraftKings and FanDuel Classic, the web app includes a **3-max tournament**
preset. It generates three lineups with three-player uniqueness, allows strong
non-QB cores, limits each unlocked player to two lineups, requires both the
QB stack partner and opponent bring-back to project for at least seven points,
prevents the same QB/pass-catcher/bring-back trio from repeating, and enables
an opponent bring-back. Custom portfolios set exposure as
an exact number of appearances instead of an ambiguous percentage. Portfolio
results show unique-QB count, maximum exposure, average lineup overlap, the
primary stack in each lineup, and warnings for concentration, projection drop,
low coverage, and selected injury/status flags.

Historical forecasts also include empirical floors and ceilings. These are the
20th and 80th percentiles of up to eight games played before the target week,
scaled within a bounded range for the current median projection. The 3-max
preset builds two balanced lineups with a 70% median / 30% ceiling objective,
then a third ceiling-focused lineup with a 30% median / 70% ceiling objective.
It generates a candidate pool and selects the entire three-lineup portfolio
together, balancing projection and pairwise overlap under the exposure limits.

Optional projected ownership can be uploaded in the format shown in
`examples/ownership.csv`. Required columns are `name`, `team`, and
`projected_ownership`; `platform_id` is optional. Ownership is merged into the
existing forecast and never replaces projected points. When ownership is
available, the 3-max objective subtracts 0.05 fantasy points per ownership
percentage point to introduce a modest leverage preference. The preset enables
that penalty only when ownership covers at least 75% of projected players, so
missing rows are not silently treated as trustworthy zero-ownership plays.

Historical forecasts apply a conservative role gate: when at least two
current-season team games are available, a player with fewer than two recent
opportunities per game and a platform fantasy average of two points or less is
left unprojected. This prevents an old starter workload from making a current
backup look like value. The 3-max preset also requires an opponent bring-back
to project for at least seven points. Searchable lock/exclude controls remain
available for late depth-chart and injury news that historical data cannot see.
For players with activity in multiple current-season games, opportunity volume
also receives a bounded 0.75x–1.15x trend adjustment based on the two most
recent games. Missing games alone do not trigger this adjustment, which avoids
automatically treating an injury absence as a lost role.

The 3-max preset also requires stack partners and bring-backs to have at least
a 12-point historical ceiling. Every unlocked player is capped at two of the
three lineups; an explicit lock overrides that cap and places the player in all
three. Before export, the app audits unavailable and questionable players,
oversized cores, excessive pairwise overlap, and stack ceiling requirements. An
`OUT`, `O`, or `IR` selection blocks platform exports.

An optional official contest-entry template can be uploaded after lineup
generation. The app fills the Classic roster columns while preserving entry
IDs and contest metadata. A downloadable run archive contains `manifest.json`,
the complete projection snapshot, and generated lineups for reproducibility
and later backtesting.

## Single-game contests

Salary import automatically detects DraftKings Showdown and FanDuel Single
Game. Both use one 1.5x-points/1.5x-salary multiplier slot and five FLEX slots.
DraftKings paired CPT/FLEX rows are collapsed into one logical player so the
same athlete cannot occupy both roles.

The web app includes a Showdown 3-max tournament preset. It caps general and
Captain/MVP exposure at two of three lineups, requires at least two unique
players and one quarterback per lineup, limits a lineup to four players from
one team, and restricts the multiplier slot to QB, RB, WR, or TE players with
at least a 20-point multiplied historical ceiling. Two lineups use a balanced
70/30 median-to-ceiling objective and the third uses a 30/70 ceiling objective.
The three lineups are selected jointly, the designated ceiling lineup must have
the highest modeled ceiling, and no lineup may use more than one combined
kicker/defense. Use the Showdown exclusion control for inactive players and
backups who are not expected to play. The preset removes zero-projection players
from consideration and only quarterbacks projecting at least five points can
satisfy its quarterback requirement.
WR and TE multiplier selections must include their quarterback, defenses may
face at most one opposing offensive player, and the joint portfolio limits the
median projection spread between any two lineups to 12 points.

Historical single-game forecasts include kickers using made field goals by
distance and extra points. Portfolio generation supports overall exposure,
pairwise uniqueness, and a separate `--max-multiplier-exposure` cap for CPT or
MVP selections.

## Backtesting and slate archives

Summarize a FanDuel field export with `dfs-field-report results.csv`. The
parser reports ownership, score percentiles, and lineup duplication without
requiring historical salaries. `evaluate_projections` calculates matched-player
MAE, RMSE, bias, and correlation.

Archive pre-lock inputs for future full contest replay:

```bash
dfs-archive-slate --label 2026-week-04 \
  --file samples/DKSalaries.csv \
  --file samples/FanDuel-NFL-2026\ EDT-10\ EDT-04\ EDT-134747-players-list.csv
```

Each archive includes SHA-256 checksums and a UTC capture timestamp.

The model forecasts opportunity (attempts, carries, and targets) separately
from efficiency. Efficiency rates are shrunk toward position-level league
rates, while current-team games with no recorded usage count as zero-opportunity
evidence. This keeps small samples and obsolete starter roles from dominating.

Pregame context then applies bounded adjustments for opponent passing/rushing
efficiency allowed, market-implied team points, spread-driven game script, and
outdoor wind. Current injury automation is deliberately not sourced from
nflverse because its injury feed has no data after the 2024 season; platform
`OUT`/`O`/`IR` statuses remain enforced.

Once the two files cover the full slate, optimize them with:

```bash
PYTHONPATH=src python -m dfs_optimizer.cli samples/DKSalaries.csv \
  --stat-projections path/to/offense.csv \
  --defense-projections path/to/defenses.csv
```
