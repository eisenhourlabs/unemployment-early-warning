# Pre-registered test T4: a score for material events

Written 2026-11-13, **before the test code was written or run**, and committed to Git before the test code (the commit
history shows the order). Review finding M2 (part 3). Template: `docs/phase4_model_tests.md`; script pattern
`src/model/state_candidates.py`. The question, procedure and rule below are copied from the review's work-package
specification without change; the "Implementation points" section fixes, before any run, the details the
specification leaves open. Anything found after the run is reported, never used to change the rule.

## Question
Can the same model predict events that matter for an insurer (unemployment up by a point or more) rather than any
event?

## Procedure
- `src/model/score.py` functions unchanged, called from a new script `src/model/material_target.py`.
- Target: an event with `ur_peak_rise_pt >= 1.0` starts within the next 12 months. Events used: #1, 2, 4, 5, 8, 9, 12
  (and #13 handled as in the main model: its window excluded). That is `load_events(drop=[3, 6, 7, 10, 11, 14, 15])`
  with the horizon set to 12.
- Same 8 inputs (`score.py` `FINAL_FEATURES`), weights >= 0, same cross-validation, expanding window from 1980.
- Primary window 1980-2026; 2000-2026 reported (it holds 2 such events).
- Metric: Brier skill vs. the training base rate; 90% interval by 2-year block bootstrap, 5,000 draws, seed 20261111.

## Rule (fixed)
Show a second probability only if skill on 1980-2026 is >= +0.05 AND the 5th percentile of the bootstrap is above 0
AND both hold with claims as first published from 2010. Otherwise record "not adopted" and show nothing.

## Implementation points (fixed before the run)
1. **Horizon.** `score.py` reads its module setting `HORIZON` (6 in the main model) in `target()`, in the
   cross-validation gap and in the re-fit's "outcome known" cut-off. The script sets `S.HORIZON = 12` before building
   the target and fitting, exactly as `score_followups.py` does for the 3- and 12-month scores. No function is edited.
2. **Events.** `S.load_events(drop=[3, 6, 7, 10, 11, 14, 15])` keeps #1, 2, 4, 5, 8, 9, 12, 13. As in the main model,
   #13 stays in the list (so months before 2020 count toward it) and the 2020 window (`score.py` `EXCLUDE_2020`) is not
   scored or fitted. Months inside the dropped events are ordinary (usable) months, as `load_events(drop=...)` already
   does for the main model's sensitivity runs. The check `ur_peak_rise_pt >= 1.0` in `data/model/events.csv` is printed
   and must give exactly the kept list; any other result stops the test.
3. **Expanding window from 1980**: `S.run_oos(F, target, status, FINAL_FEATURES, 1980, nonneg=True)`: fitted from 1968
   (`FIRST_FIT`), re-fitted each January from 1980 on the months whose 12-month outcome was known, predicting that
   year's months.
4. **Scored months**: `usable` months (outside the kept events and the 2020 window, outcome known) from 1980-01 (primary)
   and from 2000-01 (reported). Skill = 1 - Brier(score) / Brier(training base rate), the base rate being the share of
   y = 1 among each re-fit's training months (`score.py` `Fitted.base`).
5. **Bootstrap**: `score_uncertainty.bootstrap_skill` (whole 2-calendar-year blocks, resampled with replacement, as many
   blocks as exist; draws with no event are skipped because skill is undefined there), 5,000 draws, seed 20261111; the
   5th percentile is the lower end of the 90% interval. A fresh generator with the same seed for each basis and window.
6. **Claims as first published**: the three claims inputs (`claims_low`, `claims_yoy`, `cont_yoy`) replaced by their
   first-published versions (`*_v` columns of `features_monthly.csv`, from 2010; today's values before), as in
   `score.py`'s claims-vintage run and `state_candidates.py`; the model is re-fitted on that frame. "Both hold with
   claims as first published from 2010" = skill >= +0.05 and 5th percentile > 0 on that basis over the same primary
   window 1980-2026. Reported first (work-package rule 3), then revised claims; 2010-2026 reported for information.
7. All four conditions are needed: revised skill >= +0.05; revised 5th percentile > 0; first-published skill >= +0.05;
   first-published 5th percentile > 0.

## Expectation
Fails. The 6-month version on the same events scored -0.22 (1980-2026) and -0.90 (2000-2026) in the review: it rises
before both recessions since 2000 but is far too high in two dozen other months. If it fails, the historical split
already on the site after WP2 ("about 1 red month in 5 was followed by an event tied to a recession") is the right
product.

## If it passes
A second probability would change the model's output, so it would enter through the January 2027 re-fit pull request
(work-package rule 5), with Troy's approval before anything appears on the site.

## If it fails
Nothing changes. "Not adopted" is recorded in `docs/decisions.md` and `docs/model.md`.

## Outputs
`src/model/material_target.py` -> `data/model/material_target_results.csv` (basis x window: months, event months, Brier,
base Brier, skill, 5th / 95th percentiles, rule checks) and `material_target_predictions.csv`, results in docs/model.md
section 11, outcome in docs/decisions.md.
