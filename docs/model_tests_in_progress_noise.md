# Pre-registered test T3: wider ranges once an event is under way

Written 2026-11-13, **before the test code was written or run**, and committed to Git before the test code (the commit
history shows the order). Review finding F2 (part 3). Run after review WP4 Part D, so event dating in the forecast
backtest is real-time (`src/model/realtime_events.py`). Template: `docs/phase4_model_tests.md`. The problem, change,
evaluation and rule below are copied from the review's work-package specification without change; the
"Implementation points" section fixes, before any run, the details the specification leaves open. Anything found after
the run is reported, never used to change the rule.

## Problem being tested
For origins inside an event that has lasted 3+ months (50 since 2000, as measured by the review before WP4), the 80%
range for the unemployment rate held 74% / 66% / 60% of outcomes at 3 / 6 / 12 months and outcomes were above the 90th
percentile 22% / 32% / 36% of the time. In the 2008 event: 62% / 58% / 50%.

## Change under test
`src/model/forecast.py`, in-progress branch (an event under way for 3+ months: deterioration weight 1, paths picked up
at the event's current age): the noise added to an in-progress draw is resampled from the residuals of past
in-progress forecasts, not from the quiet-months baseline residuals.

Definition: for every earlier origin o that was inside an event of age >= 3 months, whose target period is already
known at the current origin, residual = realized change over the horizon - the median of the event-path changes used
at o. Pool over origins inside earlier events only. If fewer than 30 such residuals exist, use the quiet-months
residuals multiplied by 1.5.

## Evaluation
Run `forecast.py --from 1985` with and without the change. Report by regime (the WP3 script,
`src/model/forecast_regimes.py`) for 1985-1999 and 2000-2026: `cover80`, `above_q90`, `rmse_ratio`.

## Rule (fixed)
Adopt only if, for the unemployment rate in 2000-2026:
- in-progress `cover80` >= 0.70 at every horizon, AND
- overall `cover80` stays within 0.75-0.85 at every horizon, AND
- the overall RMSE ratio changes by less than 0.02 at every horizon, AND
- no shown target-horizon fails the existing gate.
Otherwise keep the model and the WP3 wording.

**Not evidence.** Scaling the upper half-widths of the in-progress fans by 1.5 after the fact lifts coverage to
88% / 82% / 76% (2.0: 90% / 88% / 86%). That only shows the size of the shortfall.

## Implementation points (fixed before the run)
1. **Option, not a replacement.** The change runs as `python src/model/forecast.py --from 1985 --option ipnoise`,
   which writes `forecast_backtest_ipnoise.csv` and `forecast_evaluation_ipnoise.csv` beside the existing files (the
   existing `--option` mechanism). "Without the change" is the committed `forecast_backtest.csv` /
   `forecast_evaluation.csv` from the `--from 1985 --live` run of test T1 (the same code path; T1 showed it reproduces
   main exactly; the live origin is not a month start and is never scored). Nothing in `data/model/` on main is
   overwritten.
2. **"Inside an event of age >= 3 months"** at an origin o = the real-time event state (as in the backtest since WP4):
   an event is under way at o and has lasted 3 or more months counting its real-time provisional start month as 1
   (exactly the condition that sends o down the in-progress branch). Origins in the 2020 window (`covid_window` for
   that horizon) are never pooled, as they are never used for fitting.
3. **"Earlier events only"**: o's real-time event start is before the current origin's real-time event start (so the
   event now under way never supplies its own residuals).
4. **"Target period already known at the current origin"**: o's target period (latest published period at o plus the
   horizon) is in the series as published at the current origin's date (unemployment rate: the ALFRED vintage of that
   day; claims rates: today's figures cut back by the release lag, as everywhere in the backtest).
5. **"Realized change"** = (value of o's target period as published at the current origin) - (o's level at origin),
   on the target's scale (points for the unemployment rate, log change for the claims rates), so the residual uses only
   what was known at the current origin.
6. **"Median of the event-path changes used at o"** = the median of the candidate event-path changes (`det`, before
   resampling) that the in-progress branch builds at o, computed with the same candidate rule. Origins before the
   backtest start (1968-1984) are included in the pool: their candidate changes are computed with the same rule.
7. The pool is built separately for each target and horizon. Noise draws: 4,000 resampled from the pool (or from the
   quiet residuals x 1.5 when the pool has fewer than 30), using the same random-number generator as now. Origins that
   are not in progress are unchanged in method (their draws can differ only through the random-number stream).
8. **Measures** come from `forecast_regimes.py`: origins from the first day of a month, realized known, 2020 window
   excluded; windows 1985-01 to 1999-12 and 2000-01 on; "in-progress" = regime "during an event", "overall" = "all".
   The RMSE ratio change = (ratio with the change) - (ratio without), at each horizon, absolute value < 0.02.
9. **"Shown target-horizons"** = the fans on the site today: unemployment rate 3 / 6 / 12 months and continuing claims
   rate 13 weeks (26 weeks was dropped in WP4 for failing the gate). The existing gate (`forecast.py` `evaluate`,
   2000-on excluding 2020): |cover50 - 0.5| <= 0.10, |cover80 - 0.8| <= 0.10 and RMSE ratio < 1. Each must pass with
   the change.
10. Claims as first published (work-package rule 3): as in test T1, the fans exist only on claims as we hold them
    today; no first-published fan backtest is built. Stated as a limitation.
11. **If adopted**: the matching change to `src/model/live.py` `fan()` (and the frozen model, which would have to carry
    the pooled in-progress residuals) is built for the January 2027 re-fit pull request, not mid-year (work-package
    rule 5). It does not affect this test, which is a backtest. If not adopted, it is not built.

## Expectation
None stated in the specification. The after-the-fact 1.5x scaling (not evidence) shows the shortfall is large; whether
past in-progress residuals are numerous and wide enough to close it, without moving the middle by 0.02 or more in RMSE
ratio, is the open question.

## Outputs
`data/model/forecast_backtest_ipnoise.csv`, `forecast_evaluation_ipnoise.csv`,
`data/model/forecast_in_progress_noise_test.csv` (window x target x horizon x regime x with / without), results in
docs/model.md section 11, outcome in docs/decisions.md.
