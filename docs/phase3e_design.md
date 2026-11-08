# Phase 3e Design Brief: Early Warning on the Site

Approved by Troy, 2026-11-08 (decisions at the end).

## Summary

Stage 3e puts the Phase 3 model on the "Unemployment Watch" site:
- the early-warning score and its colour on the Overview;
- a new **Outlook** page with the full detail (score history, triggers, forecasts, track record, methodology);
- fans and stress paths on the unemployment-rate and continuing-claims charts;
- a next-release nowcast;
- signal colours on the Leading page;
- downloads of everything the model produces;
- automation: weekly live runs, a permanent archive, alerts (off), and a January re-fit that opens a pull request.

Everything follows the approved model (docs/model.md sections 5.10 and 6) and the Phase 2 conventions (docs/phase2_design.md).

**Unchanged rules:**
- public data only, free sources;
- no employer name, logo or data; no "footprint" wording; no state counts;
- IUI is spelled out only in the "why it matters" lines;
- alerts stay off (`ALERTS_ENABLED=false`);
- the FRED key lives only in GitHub secrets and `config/.env`.

## What the site shows (from the approved decisions)

| Item | Shown | Rule |
| --- | --- | --- |
| Early-warning score (6-month) | Overview panel + Outlook | Number up to 35%; above it, "elevated" (35–50%) or "more likely than not" (50%+). Colour with hysteresis: amber from 20% until below 15%, red from 50% until below 40% |
| 3- and 12-month probabilities | Outlook only | Each beside its long-run base rate (7.5% and 30%); coherent (3 ≤ 6 ≤ 12) |
| Layer 1 triggers | Outlook table; Leading page colours | New overall rule; panel 1, 2, 4, 6, 8; temp help and manufacturing as context only |
| Unemployment-rate fan | Overview chart (+ Outlook table) | 3 / 6 / 12 months, 50% and 80% bands; 12 months labeled "lower confidence" |
| Continuing-claims-rate fan | Duration page (+ Outlook table) | 13 and 26 weeks; 52 weeks not shown (failed coverage) |
| Initial-claims-rate fan | **Not shown** | Note on Job Losses explains why |
| Stress paths (2001-type, 2008-type) | Overview, Job Losses, Duration | Behind a toggle, off by default, labeled "what-if, not a forecast" |
| Nowcast of the next unemployment-rate release | Overview chart marker + Outlook | ±0.2 point range (covers about 80% historically) |
| FOMC SEP median | Overview chart marker + Outlook forecast table | Q4 average; labeled with its release date. Shown as a FRED series reference only, no download |
| SPF, Chicago Fed | **Not shown** | Terms (docs/model.md section 6) |

## Shared rules for model output

- **One "as of" set per run.** Each live run reads everything published by the run date and writes one result set:
  the score, colour, triggers, fans, nowcast and stress paths. All of them start from the same values. Every panel shows
  "As of <date>: claims through week ending <date>; unemployment rate through <month>".
- **Colour comes from history.** The displayed colour is computed from the stored score history with the hysteresis
  rule, never from today's value alone: the previous colour plus the new score gives the new colour. The colour always
  carries a text label (Green / Amber / Red) and an icon, never colour alone.
- **Fans and markers only in today's view.** Fans, nowcast, FOMC and stress-path elements appear only when the page's
  time range includes today. Recession views and earlier ranges show history only.
- **Missing or stale outputs never break the build.** If a model file is missing or older than its allowed age, the
  panel shows the last good values with "as of" and a visible note. Examples: "Score not updated since 12 Nov: model run
  failed"; "Release delayed: the September jobs report has not been published". The rest of the page builds normally.
- **Words, not just numbers.** Above 35% the score shows its band in words, with the number in the tooltip only:
  "elevated (about 40%)".

## Page wireframes

### 1. Overview — "Where are we this week?"

```
+----------------------------------------------------------------------------------------------+
| EARLY-WARNING SCORE                                          As of Sat 7 Nov: claims to 31 Oct |
| [ ● GREEN ]  2%  chance in the next 6 months         (▼ 0.6 pt vs. last week)                  |
| The chance that new claims break out (a jump of 25%+ above their 52-week low) or unemployment  |
| starts rising, within 6 months; past alerts include short scares as well as recessions.        |
|                                                                                              |
| What's moving it:                                                                            |
|  ↓ New claims are near their lowest level of the past year            (pulls the score down)  |
|  ↓ Regional factory surveys are strong                                 (pulls the score down)  |
|  ↓ Financial conditions are looser than average                        (pulls the score down)  |
|                                                                                              |
| [2-year history line, 0–100%, amber 20% and red 50% guide lines, colour band underneath]       |
| Details, other horizons and track record → Outlook                                            |
+----------------------------------------------------------------------------------------------+
| 5 headline tiles (as Phase 2)                                                                 |
+----------------------------------------------------------------------------------------------+
| What changed this week (as Phase 2, plus one rule: "The early-warning score moved from X to Y")|
+----------------------------------------------------------------------------------------------+
| UNEMPLOYMENT RATE                                     [ ] Show what-if paths (not a forecast) |
|   history line ───────────╮                                                                   |
|                           ├─ fan: 50% band (dark), 80% band (light), median line              |
|                           │   3 mo · 6 mo · 12 mo ("12 months: lower confidence")             |
|   ◆ Next release nowcast (November, published 4 Dec): available after 26 Nov; once it is:      |
|     "4.1% (±0.2)" as a diamond with a range bar                                               |
|   ▲ FOMC median for Q4 2026: 4.1% (Sep 2026 projections)                                      |
|   Footer: "Fan = our forecast range: 50% and 80% of outcomes in testing fell inside the        |
|   bands. Since 2022 the middle line has run 0.1–0.3 pt below what happened."                  |
+----------------------------------------------------------------------------------------------+
| Claims rates, small pair (as Phase 2)                 | Release calendar (as Phase 2)          |
+----------------------------------------------------------------------------------------------+
```

- **Score number:** shown up to 35% ("2%", "28%"). From 35% to 50% the panel reads "**Elevated**"; at 50% and above,
  "**More likely than not**". The number appears only in the tooltip ("about 62% in testing terms").
- **Colour:** from the hysteresis rule on stored history. Label and icon: ● Green / ▲ Amber / ■ Red.
- **Change vs. last week:** the difference from the previous live run, in points (or "unchanged").
- **Top 3 drivers:** the three largest contributions by absolute size, from fixed plain-English templates per input,
  each ending "(pushes the score up)" or "(pulls the score down)". Inputs with zero weight are never listed.

  | Input | Up template | Down template |
  | --- | --- | --- |
  | Initial claims vs. 52-week low | "New claims have risen {x}% above their low of the past year" | "New claims are near their lowest level of the past year" |
  | Sahm indicator | "Unemployment's 3-month average is {x} pt above its low of the past year" | "Unemployment is close to its low of the past year" |
  | Temp help | "Temporary-help jobs fell {x}% over six months" | "Temporary-help jobs grew over six months" |
  | Manufacturing surveys | "Regional factory surveys are weak" | "Regional factory surveys are strong" |
  | NFCI | "Financial conditions are tighter than average" | "Financial conditions are looser than average" |
  | Yield curve | "The yield curve was inverted within the past 18 months" | "The yield curve has not been inverted recently" |

- **History line:** 2 years of weekly scores. Before launch, the weekly out-of-sample backtest scores
  (`data/model/score_weekly.csv`), dotted and labeled "backtest"; from launch, the live weekly runs, solid (decision 4).
- **Unemployment-rate chart:** the Phase 2 chart, plus the fan, the nowcast marker (diamond with a ±0.2 bar) and the FOMC
  marker (triangle at mid-Q4).
  - The what-if toggle adds the 2001-type and 2008-type paths, dashed, labeled "What-if: a 2001-type downturn starting now
    (not a forecast)".
  - If the nowcast isn't available yet: "Next nowcast after 26 Nov (needs the reference-week claims)". If it bridges a
    missing month: "Nowcast for November covers two months (October was not collected)".

### 2. Outlook (new page, after Overview in the navigation)

```
+----------------------------------------------------------------------------------------------+
| OUTLOOK                                                                As of Sat 7 Nov 2026   |
| [ ● GREEN ] 2% — chance of a new claims breakout or a rise in unemployment within 6 months   |
+----------------------------------------------------------------------------------------------+
| SCORE HISTORY since 1980                                                                       |
| [line 0–100%, amber/red guides; events shaded (blue recession / orange scare); 2020 hatched] |
| 1980–1999 "pseudo out of sample" (lighter line) | 2000–launch "out of sample" | launch– "live" |
| Note: "2020: the pandemic was not foreseeable from these inputs; it is not used to fit."       |
+----------------------------------------------------------------------------------------------+
| OTHER HORIZONS                                                                                 |
|  Within 3 months:  0.4%   (long-run average 7.5%)                                              |
|  Within 6 months:  1.8%   (long-run average 15%)                                               |
|  Within 12 months: 32%    (long-run average 30%) — "about normal for a 12-month window"        |
+----------------------------------------------------------------------------------------------+
| WARNING TRIGGERS (Layer 1)            Overall: ● Green (rule: red if 1, 2 or 4 is red; ...)    |
|  # | Rule                                   | Value     | Colour  | Last change               |
|  1 | Sahm indicator                         | 0.00 pt   | ● Green | to green, Mar 2026        |
|  2 | New claims vs. 52-week low             | −1.1%     | ● Green | to green, Jul 2026        |
|  4 | Continuing claims vs. a year ago       | −12.2%    | ● Green | ...                       |
|  6 | Yield curve (long lead, often 12+ mo)  | ...       | ● Green | ...                       |
|  8 | Financial conditions (NFCI)*           | −0.46     | ● Green | ...                       |
|  * real-time history only since 2011                                                          |
+----------------------------------------------------------------------------------------------+
| FORECASTS                                                                                      |
|  Target                    | Horizon | Median | 50% range  | 80% range  | Benchmark            |
|  Unemployment rate         | Nov nowcast | after 26 Nov | — | ±0.2 once available |          |
|                            | 3 months | 3.9%  | 3.8–4.1    | 3.7–4.2    |                       |
|                            | 6 months | 3.8%  | 3.7–4.0    | 3.5–4.1    | FOMC Q4 2026: 4.1%    |
|                            | 12 months (lower confidence) | 3.7% | 3.4–4.1 | 3.2–4.7 |               |
|  Continuing claims rate    | 13 weeks | 1.07%  | ...       | 1.02–1.13  |                       |
|                            | 26 weeks | 1.04%  | ...       | 0.97–1.14  |                       |
|  Footnote: "Professional forecasters' consensus has been a better single-number forecast than |
|  our median; the value of these fans is the range and the downturn tilt."                      |
+----------------------------------------------------------------------------------------------+
| TRACK RECORD                                                                                   |
|  Live: "What we said 3 and 6 months ago vs. what happened" — table, from launch only.          |
|        Until the first 3 months have passed: "First entries from February 2027."               |
|  Backtest (clearly labeled): coverage and accuracy table 2000–2026, event panels.              |
+----------------------------------------------------------------------------------------------+
| METHODOLOGY (plain English, collapsible sections)                                              |
|  What counts as an event · Inputs and their weights (today's table) · Why the score was high   |
|  in 2024–26 (the A1 paragraph) · The 2022 claims-revision effect · Why scores above 35% are    |
|  shown in words · What the fans can and can't do (consensus beats our median; the 2022–26 lean)|
|  · 2020 · Limits: two recessions since 2000, scares count as events, inputs revised before 2011 |
+----------------------------------------------------------------------------------------------+
```

- **Score history:** monthly out-of-sample scores 1980–launch, then weekly live scores. The colour band under the line is
  computed with hysteresis over the whole history.
- **Trigger table "last change":** the month (week, once live) of the most recent colour change, and its direction.
- **Track record:** read only from `data/archive/` (live runs). The backtest table and event panels come from the 3d files
  and are labeled "Backtest (tested on history; not live forecasts)".

### 3. Job Losses — claim frequency

```
| SA INITIAL CLAIMS RATE (as Phase 2)                    [ ] Show what-if paths (not a forecast) |
|   history; what-if paths 2001-type / 2008-type from today's level                              |
|   Score driver line: "In the early-warning score, new claims are currently the largest         |
|   downward pull."  (or "...the largest upward push")                                           |
|   Note: "We don't show a fan for initial claims: in testing it was no more accurate than      |
|   assuming no change. The early-warning score is our forward view of new claims."             |
```

The other Job Losses charts are unchanged.

### 4. Duration — claim severity

```
| SA CONTINUING CLAIMS RATE                              [ ] Show what-if paths (not a forecast) |
|   history + fan at 13 and 26 weeks (50% / 80%)                                                |
|   Note: "52-week ranges are not shown: in testing they were too narrow (80% bands held only   |
|   67% of outcomes)."                                                                          |
```

### 5. Leading Indicators

- The summary table gets the Layer 1 colours for triggers 6 (yield curve, "long lead, often 12+ months") and 8
  (NFCI, "real-time history only since 2011").
- Temp help and the manufacturing surveys appear as "context — not counted in the overall status", with no colour.
- Charts are unchanged.

### 6. Data & Downloads (new section "Early-warning model")

| File | Contents | As of |
| --- | --- | --- |
| `data/model/score_history` (CSV, XLSX) | Month (1980–) and week (live): 3/6/12-month probability, displayed colour, basis (pseudo out of sample / out of sample / live) | each row |
| `data/model/trigger_history` | Monthly trigger values and colours since 1967, with the data basis | each row |
| `data/model/forecast_archive` | Every live run's fans: target, horizon, median, 10/25/75/90 percentiles, deterioration weight | run date |
| `data/model/stress_paths` | Today's what-if paths | run date |
| `data/model/nowcast_history` | Every nowcast with its range, the first release and the error | release date |

- No SPF data. The FOMC SEP is listed as "FRED series UNRATEMD" with a link, not as a download.
- Every XLSX gets an About sheet that says "model output, not official statistics".

### 7. About

- One line in "Updates" on the model's refresh and re-fit schedule.
- A link to Outlook → Methodology.

## Behaviour

- **Time control:** as described under "Fans and markers only in today's view" above.
- **Delays and shutdowns:**
  - The release calendar knows each expected date. If a release is past due and the data hasn't arrived, the affected
    panels keep the last good values, with "as of" and a "Release delayed" label.
  - The score keeps its last value, and the weekly change shows "no new claims data".
  - The nowcast states which months it bridges.
- **Rounding:** score to whole percent below 10% ("1.8" → "2%"; "<1%" below 0.5%). Rates to the published precision.
  Fans to 0.1 point (unemployment rate) or 0.01 (continuing claims rate).

## Automation and governance

### Weekly and monthly live runs

The existing **Refresh data** workflow gets a new step after the fetchers and before the site build:
`python src/model/live.py`. `live.py` will be a new script in 3e-3, using the frozen model.

1. **Check for new inputs.** If there is a new claims week or a new unemployment-rate month since the last archived run,
   continue. Otherwise skip (no new archive file); the site rebuilds from the last run. In practice that means one run
   each Thursday after the claims release, and one after each jobs report.
2. **Compute** `features_at(run date)`, then the 3/6/12-month probabilities (coherent), the colour (hysteresis on the
   stored history), the triggers, the fans, the nowcast (once the reference-week claims exist) and the stress paths. All
   use the **frozen** model, so coefficients, residuals, event paths and climatology never change between re-fits.
3. **Write** `data/archive/YYYY/YYYY-MM-DD_<claims-week>_<ur-month>.json` (or .csv). The file is opened in "create
   only" mode, so **the run fails rather than overwrite an existing file**.
4. **Append** the run to `data/model/live_history.csv`, which the site reads.

### January re-fit (a separate workflow, opens a pull request)

**Workflow `refit-model.yml`:** on a schedule (mid-January), plus a manual button.

1. Runs the full modeling chain:
   - ALFRED vintages;
   - events (unchanged unless a new event has started; a new event needs Troy's classification first);
   - triggers, score, follow-ups and forecast backtest.
2. Writes the new frozen model `data/model/frozen/model_<year>.json`, plus residuals and paths.
3. Writes a summary diff, `reports/refit_<year>.md`:
   - old vs. new coefficients;
   - today's score and fans under the old and new model;
   - change in backtest skill and coverage;
   - any target × horizon that now fails the gate.
4. Pushes to branch `refit-<year>` and opens a pull request with `gh pr create`. That needs the repository setting
   "Allow GitHub Actions to create and approve pull requests" (see decisions).
5. **Nothing changes on the site until Troy merges.** The live run always uses the newest frozen model on `main`.

### Alerts (built, `ALERTS_ENABLED=false`)

Sent on any colour change under the hysteresis rule, and on a failed refresh. Message text:

> **Unemployment Watch: early-warning colour changed to AMBER**
> The 6-month early-warning score is 24% (last week 17%), as of claims for the week ending 21 Nov 2026.
> It entered amber at 20%; it stays amber until it falls below 15% or rises to 50% (red).
> Main drivers: new claims have risen 16% above their low of the past year (pushes up); temporary-help jobs fell 1.2%
> over six months (pushes up); financial conditions are looser than average (pulls down).
> Details: <site>/outlook.html

> **Unemployment Watch: weekly refresh failed**
> The refresh run of Thu 19 Nov 2026 failed at step "<step>". The site still shows the results as of <last good date>.
> Run log: <link to the GitHub Actions run>

### Failure handling

- The model step never stops the site build. If it fails, the build uses the last archived run, and the pages show the
  stale-data note.
- The Phase 2 data-quality checks still fail the run on stale or missing Tier 1 data, as now.
- `scikit-learn` moves from `requirements-dev.txt` to `requirements.txt`, since the live run needs it in the cloud.

## Build stages (proposed)

| Stage | Contents | Ends with |
| --- | --- | --- |
| **3e-1 Model output + Overview + Outlook** | `live.py` and the frozen model file (run locally); Overview score panel, unemployment-rate fan, nowcast and FOMC markers, what-if toggle; Outlook page; browser check extended (no "footprint", colour labels present, fans hidden outside today's range) | Local review, then a Pages link |
| **3e-2 Claims pages, Leading, Downloads** | Job Losses note + what-ifs; Duration fan + what-ifs; Leading colours and context labels; Data & Downloads model section; About line | Pages link |
| **3e-3 Automation, archive, alerts** | Refresh-workflow model step, `data/archive/` (create-only), `live_history.csv`, `refit-model.yml` (PR), alerts wired off, stale-output handling; one dry run of each workflow | Pages link + a test pull request from the re-fit workflow |

## Decisions (settled 2026-11-08)

| # | Question | Decision | By |
| --- | --- | --- | --- |
| 1 | Reviewing each stage | Review locally first (preview server + browser check), then merge the stage into `main` and publish; the Pages link follows the merge | Troy (recommended option) |
| 2 | Repository setting for the re-fit pull request | Switch on "Allow GitHub Actions to create and approve pull requests" in stage 3e-3, when the re-fit workflow is built | Troy |
| 3 | Wording for the fans' recent lean | "Since 2022 the middle line has run 0.1–0.3 pt below what happened." | Troy |
| 4 | Overview history line | **Weekly throughout:** the weekly out-of-sample scores (re-scored every Thursday since 2000 with that year's model, from stage 3d's colour-stability test) drawn **dotted and labeled "backtest"**, then the live weekly runs **solid** from launch. 2 years shown; the colour band uses the same weekly history with hysteresis | Claude (delegated): the score updates weekly and the panel shows "change vs. last week", so the line should have the same frequency; no mixing of monthly and weekly points |
