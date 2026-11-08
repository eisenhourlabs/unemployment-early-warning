# Phase 3 Plan: Early-Warning Score and Forecasts

Approved by Troy, November 8, 2026. This is the build brief for Phase 3.

## Summary

Phase 3 turns the dashboard from "here's the data" into "here's what it means": a green / amber / red early-warning score, and forecast ranges for the unemployment rate and both claims rates at 3, 6 and 12 months. All of it is backtested and explainable, and it shows its own track record.

It has three layers, from simplest to most model-driven:

1. **Rule-based triggers:** about 8 transparent rules (Sahm rule, claims jump vs. their recent low, and so on), each green / amber / red.
2. **Early-warning score:** the probability of a defined "labor-market deterioration" event within 6 months, from a deliberately simple model, shown with the indicators driving it.
3. **Forecast ranges:** 3-, 6- and 12-month fans that widen honestly and lean upward when risk rises, because unemployment rises fast and falls slowly.

**The biggest constraint is history.** Most indicators start around 1990, and our claims rates start in 1995. That gives three recessions to learn from (2001, 2008–09, 2020), one of which was a pandemic. The plan is built around that: few parameters, rules over clever models, and wide, honest uncertainty.

**All decisions are settled** (table at the end). Amber is tuned to warn early, accepting about one false amber for each real one.

## What we're predicting

The score needs a precise definition of the bad thing it warns about. The forecasts need targets and horizons.

**The event (what the score warns about).** Decided: **a deterioration event starts when either of these first happens:**

| Event leg | Definition | Why |
| --- | --- | --- |
| Unemployment leg | The unemployment rate's 3-month average rises 0.5 point or more above its low of the prior 12 months (the Sahm-rule shape, applied as an outcome) | The standard, well-tested definition of a labor-market turn |
| Claims leg | The SA initial claims 4-week average rises 25% or more above its low of the prior 52 weeks | Faster, and closer to what drives IUI claim frequency |

The score is the probability that an event starts **within the next 6 months**. Past events would include 2001, 2008, 2020 and possibly a few smaller scares; we'll list each one so you can sanity-check them.

**Forecast targets and horizons**

| Target | Horizons | Why |
| --- | --- | --- |
| Unemployment rate | 3, 6, 12 months; plus a nowcast of the next release | The headline everyone knows |
| SA initial claims rate | 13, 26, 52 weeks | Frequency of new claims |
| SA continuing claims rate | 13, 26, 52 weeks | Severity (duration) |

3–6 months is the priority, as you decided. 12-month forecasts are shown but labeled lower confidence. Any horizon that can't beat a simple "no change" forecast in backtesting won't be shown at all.

## The data constraint

How much we can trust Phase 3 depends mostly on how much history it learns from, and on whether that history is "as known at the time".

| Constraint | What it means | How the plan handles it |
| --- | --- | --- |
| **Few recessions** | Since 1995: 2001, 2008–09, 2020. Since 1967: 8 (1969–70, 1973–75, 1980, 1981–82, 1990–91, 2001, 2007–09, 2020) | Few parameters. Rules chosen for logic first, data second. Every result reported with how many events it rests on |
| **Claims rates start in 1995** | Covered employment in our DOL data starts there (pending the Phase 2 fix) | Use FRED's SA initial and continued claims levels (back to 1967) for the score's claims leg, and keep the 1995+ rates for the rate forecasts. The longer history adds five recessions |
| **2020 was a pandemic, not a business cycle** | Claims rose about 30-fold in two weeks; no indicator "led" it | Evaluate on it, but don't let it set thresholds (decision 4) |
| **Revisions** | Payrolls and some indicators are revised heavily. A backtest on today's numbers looks better than reality | Use ALFRED (FRED's archive of past vintages) for revised monthly series in the backtest. DOL claims stay current-vintage, as you decided; their revisions are mostly seasonal factors, a small effect we'll measure and state |
| **Publication lags** | JOLTS arrives about 5 weeks late, the unemployment rate about 1 week, claims 5 days | The backtest only uses what was published by each forecast date |

## Layer 1 — Rule-based triggers

Each rule is green, amber or red on its own, and anyone can see why. Starting thresholds are below; the backtest then checks each rule's lead time and false alarms, and we adjust only where the evidence is clear.

| Trigger | Amber | Red | Notes |
| --- | --- | --- | --- |
| Sahm indicator | ≥ 0.30 pt | ≥ 0.50 pt | Published by the St. Louis Fed; well tested |
| SA initial claims 4-wk avg vs. 52-week low | +15% | +25% | Same shape as the claims leg of the event |
| SA initial claims 4-wk avg vs. a year ago | +10% | +20% | Catches slow grinds the 52-week low misses |
| SA continued claims vs. a year ago | +10% | +20% | Severity side |
| Temporary help jobs, 6-month change | Negative | Below −3% | Cuts temps first |
| Yield curve (10y − 3m) | Inverted 3+ months | Re-steepening after an inversion | Long lead; shown, but given low weight in the score |
| Regional manufacturing surveys (Philly + Empire avg) | Below 0 for 3 months | Below −15 | Factory activity |
| Financial conditions (NFCI) | Above 0 | Above +0.5 | Credit tightening |

**How thresholds get checked:** for each rule and each past event, the backtest reports how many months of warning it gave, and how often it fired with no event following in 12 months. A rule that never adds warning beyond the Sahm and claims rules gets dropped, to keep the panel honest.

**Overall Layer 1 status:** red if any of the first four rules is red; amber if two or more rules are amber or red; otherwise green. This is simple on purpose; the score (Layer 2) is the nuanced view.

## Layer 2 — The early-warning score

The score is the estimated probability, 0–100%, that a deterioration event starts within 6 months. It's shown with the 3–4 indicators pushing it up or down this week.

**How it's built** (deliberately simple, given three to eight events):

1. Each candidate indicator becomes a standardized "how unusual is the recent change" value, signed so that higher always means worse.
2. A **penalized logistic regression** (a standard yes/no probability model, with a penalty that stops it overfitting a few events) estimates the event probability from 4–6 of those values.
3. Candidates: claims 4-wk avg change (year-over-year and vs. 52-week low), continued claims year-over-year, Sahm indicator, temp help 6-month change, manufacturing surveys, NFCI, yield curve. The backtest keeps only those that improve out-of-sample accuracy.
4. **Each indicator's contribution is shown** (its value × its weight), so "amber because claims are up 18% from their low" is always visible.

**Color bands.** Starting values below. Amber is calibrated in the backtest to warn early, with about one false amber for each real one; red stays at "more likely than not".

| Color | Proposed probability | Meaning |
| --- | --- | --- |
| Green | Below 20% | Normal conditions |
| Amber | 20–50% | Elevated risk: watch weekly, review assumptions |
| Red | Above 50% | A deterioration is more likely than not within 6 months |

**Fallback:** if the logistic model can't beat the Layer 1 rules out of sample, we ship an equal-weighted average of standardized indicators instead, labeled as an index rather than a probability. That's honest and still useful.

## Layer 3 — Forecast ranges

The forecasts must capture one fact above all: unemployment goes up fast and comes down slowly. So the fan should lean upward when risk rises, not sit symmetrically around a straight line.

**Method: a two-scenario mixture**

1. **Baseline path:** a simple regression of the h-month-ahead change (unemployment rate, or claims rate) on current leading indicators, estimated directly for each horizon.
2. **Deterioration path:** the average path of the target in the months after past event starts, scaled to today's level. The 2001 and 2008 events are the core; 2020 is shown separately.
3. **Mix them** using the Layer 2 probability: when the score is low, the fan hugs the baseline; as it rises, the upper band stretches toward the deterioration path.
4. **Bands:** 50% and 80% ranges, from the backtest's actual forecast errors plus the mixture.

**Nowcast of the next unemployment-rate release:** a small model using the claims weeks that fall in the survey reference week. The Chicago Fed's real-time forecast is added as a comparison marker if its terms of use allow it.

**Benchmarks shown as markers:**

| Benchmark | Source |
| --- | --- |
| No change (random walk) | Our own |
| FOMC median projection | Federal Reserve Summary of Economic Projections (FRED series to verify) |
| Survey of Professional Forecasters | Philadelphia Fed, quarterly |

**Optional, recommended: stress paths.** Two labeled what-if lines on the claims-rate and unemployment charts, "if a 2001-type downturn started now" and "if a 2008-type downturn started now", drawn from today's level. These aren't forecasts; they show what a bad case would look like for pricing and reserving discussions (decision 7).

## How we'll know it works

Two checks: a backtest before launch, and a live track record after.

**Backtest (before anything goes on the site)**

- **Rolling origin:** at each month from 2000 onward, fit only on data published by then, make the forecast, and score it later. Repeat across the history.
- **Score accuracy:** Brier score (the standard accuracy measure for probabilities) and how many months of warning it gave before each event.
- **Forecast accuracy:** error vs. the no-change forecast at each horizon, and whether the 50% and 80% bands actually contained the outcome about 50% and 80% of the time.
- **Event-by-event report:** for 2001, 2008 and 2020 (and earlier events where data allows), when each trigger and the score went amber and red, and what the fans showed 3 and 6 months before.
- **Written up in `docs/model.md`,** with plain-language results and every caveat, before you approve anything.

**Live track record (after launch)**

- Every week's score and forecasts are saved permanently. These are the one thing we never overwrite.
- The site shows "what we said 3 and 6 months ago vs. what happened", so credibility is earned in public.

**Model changes** follow a rule: re-fit once a year, or when an event happens. Every change is logged in `docs/decisions.md` with before/after backtest results. No quiet tweaking (decision 8).

## Site changes

| Where | Change |
| --- | --- |
| **Overview** | The score placeholder becomes the live panel: color, probability, change vs. last week, the top drivers, and a small 2-year history line. The unemployment-rate and claims-rate charts get their forecast fans (and stress paths, if approved) |
| **New page: Outlook** | Full detail. The score's history since 1990 with event shading. The trigger table (each rule, its value, color, and when it last changed). A forecast table (each target × horizon: central value, 50% and 80% ranges, benchmarks). The track record. The methodology in plain English |
| **Leading Indicators** | Signal colors added to the summary table, using the Layer 1 rules where they apply |
| **Job Losses / Duration** | Fans on the two claims-rate charts; trigger badges on the relevant cards |
| **Data & Downloads** | Score history, trigger history and all forecasts (with their vintages) downloadable |
| **Alerts** | Wired to the score's color changes and red triggers, still off (`ALERTS_ENABLED=false`) |

The navigation adds Outlook after Overview. Everything else keeps the Phase 2 design.

## Build stages and gates

Nothing appears on the site until stage 3e. Stages 3a–3d produce files and reports for review here first.

1. **3a — Foundation:** extend claims history to 1967 via FRED, add ALFRED vintages for revised monthly series, code the event definition, and list every historical event for your sign-off. *Gate: you approve the event list.*
2. **3b — Triggers:** compute all Layer 1 rules historically and produce the lead-time and false-alarm table. *Gate: we review thresholds together.*
3. **3c — Score:** fit and backtest the probability model, with the equal-weight fallback for comparison. *Gate: it beats the triggers alone out of sample, or we ship the fallback.*
4. **3d — Forecasts:** baseline, deterioration paths, mixture fans and the nowcast, all backtested against benchmarks. *Gate: band coverage within about 10 points of target, and each shown horizon beats no-change.*
5. **3e — Site:** Overview panel, Outlook page, fans, colors, downloads, alerts wired off, live forecast archive. *Gate: final review, as in Phase 2.*

`docs/model.md` grows with each stage, so the method is documented as it's built, not after.

## Decisions (settled November 8, 2026)

| # | Question | Decision |
| --- | --- | --- |
| 1 | Event definition | Unemployment leg (3-month average ≥ 0.5 pt above prior 12-month low) OR claims leg (SA initial claims 4-wk avg ≥ 25% above 52-week low); score = probability an event starts within 6 months |
| 2 | Forecast targets | Unemployment rate plus SA initial and continuing claims rates |
| 3 | Early warning vs. false alarms | **Amber early:** accept about one false amber for each real one. Red stays stricter (more likely than not) |
| 4 | 2020 | Evaluate on it; exclude it when setting thresholds and weights |
| 5 | Real-time rigor | ALFRED vintages for revised monthly series in backtests; DOL claims current-vintage, with the effect measured and stated |
| 6 | Forecast bands | 50% and 80% |
| 7 | Stress paths | Yes: 2001-type and 2008-type what-ifs on the charts |
| 8 | Model change rule | Re-fit yearly or after an event; before/after results logged in docs/decisions.md |
| 9 | Alerts when turned on | Score color changes plus any red trigger (still off for now) |
| 10 | New page name | Outlook |

Next: stage 3a in Claude Code, ending with the historical event list for Troy's sign-off.
