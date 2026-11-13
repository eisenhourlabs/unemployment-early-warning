# Pre-registered test T1: chance of a large rise in unemployment

Written 2026-11-13, **before the test code was written or run**, and committed to Git before the test code (the commit
history shows the order). Review finding F5. Template: `docs/phase4_model_tests.md`. The definitions, window and
adoption rule below are copied from the review's work-package specification without change; the "Implementation
points" section fixes, before any run, the details the specification leaves open. Anything found after the run is
reported, never used to change the rule.

## Question
Is the forecast fan's implied chance of a rise of 0.5 point or more in the unemployment rate reliable enough to show?

## Change under test (display quantity only; the forecast method is unchanged)
- `src/model/forecast.py`: from the simulated `levels` array of each forecast (4,000 draws), compute
  - `p_rise_050 = mean(levels >= y0 + 0.5)` for target `ur` (unemployment rate; y0 = the level at the origin, in %),
  - `p_rise_20pct = mean(levels >= 1.2 * y0)` for target `cc` (SA continuing claims rate, 4-week average).
  Stored as two new columns of `data/model/forecast_backtest.csv` (blank where they do not apply).
- `src/model/live.py` `fan()`: the same quantity in each fan horizon entry of `data/model/live_latest.json`
  (`p_rise_050` for `ur`, `p_rise_20pct` for `cc`) and as columns of `data/model/live_fans_history.csv`.
- Adding these columns must not change any existing number: they are computed after the quantiles, from the same
  draws, and consume no random numbers. Check: re-run `python src/model/forecast.py --from 1985 --live` (the
  configuration of the committed file) and compare every existing column of `forecast_backtest.csv` with the version on
  `main`; any difference stops the test.

## Evaluation
`src/model/forecast_regimes.py` writes `data/model/forecast_tail_reliability.csv`:
- rows = target x horizon x bin, for `ur` at 3 / 6 / 12 months (`p_rise_050`) and `cc` at 13 / 26 / 52 weeks
  (`p_rise_20pct`);
- bins of the stated probability: [0, 0.10), [0.10, 0.25), [0.25, 0.50), [0.50, 1];
- columns `origins`, `mean_stated` (mean stated probability in the bin), `observed` (share of origins where the
  realized value met the threshold: realized >= y0 + 0.5 for `ur`, realized >= 1.2 * y0 for `cc`);
- plus a `base_rate` row per target x horizon (all origins: `observed` = the share that met the threshold).
- Origins: from 2000-01, first day of a month, realized value known, 2020 window (`covid_window`) excluded.
- Realized values are as in the existing backtest (`realized` column: final unemployment rate; claims rates as we hold
  them today).

## Rule (fixed)
Show the probability for a target-horizon only if
- (a) `observed` rises from each bin to the next, and
- (b) every bin with 20 or more origins has |observed - mean_stated| <= 0.15.

## Implementation points (fixed before the run)
1. "Rises" means strictly greater. A bin with no origins has no `observed` value: it is skipped and the comparison is
   between consecutive non-empty bins. A target-horizon with fewer than two non-empty bins fails (a) (nothing to
   compare).
2. Thresholds are compared with a tolerance of 1e-9 (a rise of exactly 0.5 point counts: the published rate has one
   decimal, so 4.1 to 4.6 must count although 4.1 + 0.5 is not exactly 4.6 in binary floating point). The same
   tolerance applies to the stated probability and to the realized outcome. This is the convention used for the nowcast
   in review WP3.
3. Claims as first published (work-package rule 3): the forecast fans have only ever been built and tested on claims as
   we hold them today (plan decision 5), both for their inputs and for the continuing-claims target; no first-published
   version of the fans exists. This test does not build one; this is stated as a limitation, and the test is reported on
   the existing basis only.
4. The continuing-claims version is evaluated and reported under the same rule; the specification asks for a display
   only on the unemployment-rate rows, so a pass there changes nothing on the site.
5. The rule is applied to each target-horizon separately: a horizon that fails is not shown even if another passes.

## Expectation (from the review's prototype, read off the 5 stored percentiles rather than the draws)
Unemployment rate, observed share by bin (origins):
- 6 months: under 10% -> 1% (222); 10-25% -> 21% (47); 25-50% -> 56% (9); over 50% -> 89% (18); base rate 12%.
- 12 months: 1% (136); 8% (65); 40% (65); 94% (18); base rate 17%.
Expected to pass at 6 and 12 months. The continuing-claims version is untested. Today's 12-month value is expected
between 0.10 and 0.15 ("about 1 in 8").

## If it passes: display (needs Troy's approval before it goes live)
- Outlook forecast table: new column "Chance of a rise of 0.5 pt or more" on the unemployment rows that passed, printed
  as "under 1 in 10", "about 1 in 8", "about 1 in 4", "about 1 in 3 to 1 in 2" or "above 50%" (cut points 0.10, 0.17,
  0.30, 0.50), with the base rate beside it in grey ("usual: 12%" / "17%", from the `base_rate` rows).
- Overview "Where things stand", cell 3, small line: before "A stress alert, not a recession forecast." put
  "Chance unemployment is half a point or more higher in a year: {phrase} (usual: 1 in 6)." (12-month value; phrase cut
  points 0.10, 0.17, 0.30, 0.50 as above). Only if the 12-month horizon passed. Never "more likely than not".
- Display only: the fans and the model are unchanged, so it may go live once Troy approves (no re-fit needed).

## If it fails
Nothing changes on the site. The outcome is recorded in `docs/decisions.md` and `docs/model.md`.

## Unit test
`p_rise_050` of levels all equal to y0 + 1 is 1.0; all equal to y0 is 0.0.

## Outputs
`data/model/forecast_backtest.csv` (2 new columns), `data/model/forecast_tail_reliability.csv`, results in
`docs/model.md` (section 11), outcome in `docs/decisions.md`.
