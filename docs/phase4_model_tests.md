# Phase 4 stage 4e: pre-registered model tests

Written 2026-11-09, **before any test was run**, and committed to Git before the test code (commit history shows the
order). Troy delegated the approval of this document to Claude (2026-11-09). Nothing here changes the live model: a
candidate that is adopted enters only through the January 2027 re-fit pull request.

## Candidates (from docs/phase4_design.md)

| | Candidate | Definition (monthly input, signed so higher = worse) | Prior expectation |
| --- | --- | --- | --- |
| C1 | State claims diffusion | Covered-employment-weighted share (%) of the 50 states + DC whose 4-week average initial claims are up 20% or more on the same weeks a year earlier (`diffusion_ce_weighted_pct`, data/processed/states/diffusion_weekly.csv) | Plausible gain: breadth is information the national total lacks |
| C2 | Weighted claims | log(1 + weighted 4-week initial claims rate year-on-year change / 100) (`weighted_ic_yoy_pct`, weighted_weekly.csv; weights = config/state_weights.csv, held fixed for all history) | Low: close to the national NSA year-on-year input that failed A2 in Phase 3 |

The 20% threshold of C1 was fixed in the brief. C1 at 10% and 30% is reported **only** as a sensitivity check, never to
choose the threshold.

## Data as known at the time

- State claims: today's (current-vintage) ar539 data, cut back by the state release lag. **Lag = 12 days** from the end
  of a week: measured on 2026-11-09, DOL's state weekly report ran through the week ending Oct 24 (published with the
  Nov 5 release, 12 days after the week ended), one week behind the national advance figure (5 days). So the value of a
  month is the latest week w with w + 12 days <= the month's last day.
- No state vintages exist, so revisions to state data are not captured (stated limitation, as for national claims in
  Phase 3). Weights are today's, held fixed back to 1996 (stated limitation).
- Both candidates exist from January 1996 (52 weeks after ar539 starts in 1995). Before that they are missing, which
  the Phase 3 code treats as 0 ("average, no information") after standardization.

## Models and test (Phase 3 machinery, unchanged: src/model/score.py)

- Ridge logistic regression, weights >= 0, penalty chosen by time-ordered cross-validation; inputs standardized on the
  training window and capped at +/-4; 6-month horizon; events from data/model/events.csv; 2020 window excluded.
- Expanding window, re-fit each January on months whose outcome was known.
- **Baseline** = the final Phase 3 model (the eight trigger measures). **Candidate model** = baseline + C1, or
  baseline + C2. At most one candidate is added.

**Primary comparison (A), as the brief requires: the same window.** Baseline and candidate models are both fitted
only on months from January 1996, re-fitted each January, and scored on the same months: every usable month from 2000
on for which both produce a prediction (in practice from 2001: no event starts between 1996 and November 2000, so no
model can be fitted before the January 2001 re-fit), 2020 window excluded.

**Secondary comparison (B), Phase 3 convention:** both fitted from 1968 (the candidate is 0 before 1996), scored
2000-2026 excluding 2020.

## Metric and uncertainty

- Brier skill = 1 - Brier(model) / Brier(base rate of the training window). Reported: skill of each model and the
  **difference** (candidate - baseline) on identical months.
- 90% interval for the difference: block bootstrap **by episode** (5,000 draws, seed 20261109). Episodes: the scored
  months are cut 12 months before each event start (events 9, 10, 11, 12, 14, 15), giving one block per event cycle
  plus the quiet stretches between; whole blocks are resampled with replacement.
- With about a dozen events since 2000, a skill gain under roughly 0.05 is unlikely to be distinguishable from noise; the
  bootstrap interval, not this rough figure, is the reported evidence.

## Sensitivity runs (reported; also used in the adoption rule where stated)

1. Claims as first published (FRED vintages from 2010) for the three national claims inputs, as in Phase 3; state
   inputs unchanged (no vintages); comparison A, scored 2010 on.
2. The four one-off shock scares (#3, #6, #11, #14) not counted as events; comparison A.
3. C1 at 10% and 30% (comparison A).
4. Comparison B (above).

## Adoption rule

The Phase 3 rule, verbatim as recorded in docs/decisions.md (stage 3d A2): *"no variant improves as-published skill
materially without losing > 0.02 of today's-data skill"*, i.e. a new input is adopted only if it improves skill
materially and costs no more than 0.02 of skill on any other basis. Made exact for 4e, a candidate is **adopted** only
if ALL of:

1. Comparison A: skill difference >= **+0.02**, AND the lower end of its 90% bootstrap interval is **above 0**;
2. Sensitivity 1 (claims as first published, 2010 on): skill difference >= **-0.02**;
3. Comparison B: skill difference >= **-0.02**.

If both candidates pass, the one with the larger difference in A is adopted (at most one). If neither passes, the
model is unchanged and the result is recorded. An adopted candidate goes into the January 2027 re-fit pull request
(`refit-model.yml`), not into the live model mid-year.

## Outputs

`src/model/state_candidates.py` -> `data/model/state_candidates_*.csv`, results in docs/model.md section 8.
