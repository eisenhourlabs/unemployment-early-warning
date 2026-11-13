# Pre-registered test T2: the Duration watch on data as known at the time

Written 2026-11-13, **before the test code was written or run**, and committed to Git before the test code (the commit
history shows the order). Review finding I1 (part 2); builds on the Duration watch backtest of review WP5 Part A
(`src/model/severity_watch.py`, docs/model.md section 9). Template: `docs/phase4_model_tests.md`. The procedure, bands,
windows and rule below are copied from the review's work-package specification without change; the "Implementation
points" section fixes, before any run, the details the specification leaves open. Anything found after the run is
reported, never used to change the rule.

## Question
Do the band percentages of the Duration watch hold when the band is assigned with data as known at each month end?
(The WP5 backtest assigned bands with today's revised continuing claims, using the last week ending in each month
without any publication lag.)

## Procedure
- At each month end d, continuing claims vs. a year ago = `cont_yoy_of(as_known_on("CCSA", d))`
  (`src/model/triggers.py` / `src/model/realtime.py`): the 4-week average of SA continuing claims for the latest week
  published by d, against the same average 52 weeks earlier. `CCSA` is current-vintage claims cut back by the 12-day
  release lag (the project's standing rule). This is the value of the continuing-claims confirmation trigger, the same
  number the live Duration watch uses.
- From 2010, also `cont_yoy_of(as_known_on("CCSA_vintage", d))`: claims as first published (FRED vintages; the first
  vintage is September 2009, and a year of history is needed, so first-published values start in January 2010 as in
  `src/model/features.py`).
- Bands, fixed, no tuning: falling (< 0), green (0 to under +10%), amber (+10% to under +20%), red (+20% or more).
- Outcomes at month t, on final (today's) data, as in WP5: `lt_share_up` = share of unemployed out of work 27+ weeks
  (LNS13025703) up 3.0 points or more from t to t + 12; `median_up` = median weeks unemployed (UEMPMED) up 1.5 or more
  from t to t + 12. Blank when month t + 12 is not observed yet.
- Months 2019-04 to 2021-12 are excluded.
- Reported: share of months in each band followed by each outcome, and months per band, for
  - 1968-1999 and 2000-2026 on real-time (current-vintage, lagged) claims: **the rule windows**;
  - 2010-2026 on claims as first published, and 2010-2026 on real-time current-vintage claims beside it;
  - the whole sample 1968-2026 on real-time claims, beside WP5's revised-data values (information only).
  Window membership is by the band month t.

## Rule (fixed)
Show the percentages (the fractions in the WP5 and WP7 wording and the small table) only if, in BOTH 1968-1999 and
2000-2026 and for BOTH outcomes:
- red share >= 0.50,
- falling share <= 0.10, and
- the shares rise from falling to green to amber to red.
Otherwise keep the bracketed words-only wording permanently.

## Implementation points (fixed before the run)
1. "Rise" means strictly greater at each step (falling < green < amber < red).
2. A band with no months in a rule window has no share: the rule then fails for that window (all four shares are
   needed to show the four-band table).
3. The 2010-2026 first-published results are reported, not part of the rule (the specification's rule names only the
   two real-time windows).
4. The 1968 start: the first month with a value 52 weeks of continuing claims earlier, as published by the month end.
5. What "show the percentages" means on the site (WP5 Part C and WP7 cell 2): the Duration watch card headline and the
   Overview "Where things stand" duration line use the unbracketed wording (for example "about 1 time in 6",
   "1 month in 100"), and the card shows the small table from `data/model/severity_watch.csv` (today's revised data,
   1968-2026, the figures the wording was written from). The fractions themselves are not re-derived from this test.

## Expectation
Passes: continuing claims are revised little relative to a 10-20% band. Whole-sample values on revised data (WP5):
falling 0.01 / 0.02; green 0.17 / 0.10; amber 0.58 / 0.51; red 0.83 / 0.57 (`lt_share_up` / `median_up`).

## If it passes: display (needs Troy's approval before it goes live)
`T2_PASSED = True` in `src/site/duration.py` (card wording and table) and the unbracketed Overview wording in
`src/site/overview.py`. Display only: no model change, so it may go live once Troy approves.

## If it fails
The bracketed words-only wording stays permanently. The outcome is recorded in `docs/decisions.md` and
`docs/model.md`.

## Outputs
`src/model/severity_watch_realtime.py` -> `data/model/severity_watch_realtime.csv` (basis x window x outcome x band:
months, share_followed; plus the rule result), results in docs/model.md section 11, outcome in docs/decisions.md.
