# Model card: Unemployment Watch early-warning score and forecast ranges

A two-page summary of the model behind the Overview and Outlook pages. Quote numbers from this card, not from
`docs/model.md`. That file is the full working record, and it still holds results that were later replaced, for
example section 5.2 "before review". This card is reviewed at each January re-fit. A unit test
(`tests/test_model_card.py`) checks its key numbers against the model files, so the card cannot quietly go out of date.

Model in use: the 2026 model (`data/model/frozen/model_2026.json`),
frozen on 2026-11-08 on data known by 2026-01-01.
Next re-fit: January 2027 (`.github/workflows/refit-model.yml`, reviewed through a pull request).

## 1. What it estimates
- **The early-warning score** is the chance that one of two things happens within 6 months:
  - new claims jump 25% or more above their low of the past year; or
  - the unemployment rate's 3-month average rises 0.5 point above its low.

  It is a **labour-market stress alert, not a recession forecast**. Of the 14 such events since 1967 (2020 aside),
  8 were tied to a recession and 6 were short scares that faded.
- **It covers new job losses (claim frequency), not how long unemployment lasts (claim severity).** Continued
  claims had a weight of 0 in all 27 re-fits. Severity is followed separately by the Duration watch (continuing
  claims against a year ago; `docs/model.md` section 9). This is a banded indicator with a tested history, not a
  probability.
- **Colours:**
  - green below 20%;
  - amber from 20%, until the score falls below 15%;
  - red from 50%, until it falls below 40%;
  - scores of 50% and above read "High", not as a precise probability.
- **Forecast ranges** ("fans") for the unemployment rate at 3, 6 and 12 months and for the continuing claims rate
  at 13 weeks. They are built as a mixture of a quiet path and an event path, weighted by the 3-, 6- and 12-month
  scores. Other forecast lengths failed the accuracy gate and are not shown. The 12-month range has no middle line.
- **Chance of a rise of 0.5 point or more** in the unemployment rate. It is shown at 3 and 6 months only, because
  the 12-month figure failed its pre-registered test (`docs/model.md` 11.1).

## 2. Inputs and method
- Eight inputs, each measured on the data as it was published at the time (ALFRED vintages where FRED has them):
  1. the Sahm indicator;
  2. new claims against their 52-week low;
  3. new claims against a year ago;
  4. continued claims against a year ago;
  5. temp-help jobs, 6-month change;
  6. the yield curve (10-year less 3-month);
  7. the regional manufacturing surveys;
  8. the Chicago Fed financial conditions index (NFCI).
- Ridge logistic regression with weights constrained to zero or above. The penalty is chosen by time-ordered
  cross-validation. The model is re-fitted every January on what was known then.
- New claims against their low carries the most weight in every re-fit. Tested alone, it gives about half the full
  model's skill.
- Event dating: `src/model/events.py` (frozen settings `UR_RISE` 0.5, `CLAIMS_RISE` 0.25, `QUIET_MONTHS` 6). Live
  runs flag an event "under way" automatically, labelled provisional (`src/model/realtime_events.py`).

## 3. How it was tested
- **Out of sample, 2000–2026:** 236 scored months, 36 of them followed by an event, which covers only 6 distinct
  events. Each month is scored by a model fitted only on earlier data.
- **Two versions of the claims data.** Results are given first on claims **as first published** (from 2010), then
  on today's revised figures. DOL's 2023 seasonal-factor revision removed a false red in 2022 that the score would
  have shown in real time.
- **Changes after the November 2026 freeze** are allowed only after a test whose plan is written and committed
  before the test is run (template `docs/phase4_model_tests.md`). They enter only through the January re-fit.
- **2020 is left out** of fitting and testing, and reported separately.

## 4. The numbers that matter (2000–2026, out of sample)

| Measure | Claims as first published | Claims as revised today |
| --- | --- | --- |
| Red (50%+): months / followed by an event within 6 months | 39 / 44% | 27 / 56% |
| Amber (20–50%): months / followed by an event | 36 / 22% | 36 / 28% |
| Green (under 20%): months / followed by an event | 161 / 7% | 173 / 6% |
| Skill against the long-run base rate (Brier) | −0.01 (90% range −0.49 to +0.30) | +0.18 (90% range −0.07 to +0.42) |
| AUC (chance an event month scored above a quiet month) | 0.81 | 0.84 |

- **Longest run at amber or red:** 38 months, November 2022 to December 2025. Two short scares and no recession
  followed. The unemployment rate rose from 3.4% to 4.5% over the stretch.
- **Forecast ranges, unemployment rate, 2000–2026 (2020 excluded):**
  - the middle line beat "no change" (error ratio 0.82 / 0.81 / 0.78 at 3 / 6 / 12 months);
  - the 80% range held 82% / 79% / 79% of outcomes overall;
  - but only 73% / 67% / 72% once an event had been under way for 3 months or more.
- **Continuing claims rate, 13 weeks:** error ratio 0.76; the 80% range held 77% overall and 71% during events.
- **Official forecasts did better than our middle line:** the FOMC and SPF projections beat it.
- **Nowcast:** the next unemployment rate, rounded, fell within 0.2 point of the published figure 90% of the time.
  The last published rate managed 88%.

## 5. Intended use and known limits
- **Intended use:** a monitoring aid for labour-market conditions that affect unemployment, built from public data.
  The score and ranges are experimental model output with a short live record. **They are not a basis on their own
  for pricing, reserving or risk limits.**
- **The evidence is thin.** Six events since 2000 is a small sample. The skill range includes zero, and on claims as
  first published the skill is about zero. The honest position is "plausible, transparent, unproven live". The live
  record (`data/archive/`, read back into `data/model/live_scorecard.csv`) is the test that will count.
- **Overconfident above 35%:** months scored 50%+ were followed by an event about half the time.
- **Ranges are too narrow once a downturn is under way** (2008: 62% / 58% / 50%), and the middle line ran too low.
  A tested widening narrowly failed its rule and was not adopted (`docs/model.md` 11.3).
- **State UI claims are a proxy.** Eligibility rules, waiting periods and benefit limits differ from any private
  unemployment insurance. The model says nothing about one book's own claims.
- **Manual and single-maintainer steps:** event rulings, the January re-fit review, and the browser check, which runs
  on one PC.

## 6. What changed, and when
| Date | Change |
| --- | --- |
| 2026-11-08 | First frozen model (2026): final inputs, weights ≥ 0, colours 20/15 and 50/40, fans gated (`docs/model.md` 5.10, 6) |
| 2026-11-12 | Independent review, wording: "stress alert, not a recession forecast"; "High" for 50%+; skill range and hit rates by colour published; no fan middle line beyond 6 months |
| 2026-11-12 | Real-time "event under way" flag; fans switch to event mode on it. The 26-week continuing claims fan failed the gate on real-time event dates and was removed from the site |
| 2026-11-13 | Pre-registered tests: chance of a 0.5-point rise adopted for display at 3 and 6 months; Duration watch confirmed on data as known at the time; wider in-progress ranges and a material-event score not adopted. No change to the model |
